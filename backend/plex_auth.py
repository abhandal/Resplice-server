"""Plex authentication — server-side sessions with opaque session IDs."""

import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, Response, HTTPException

from backend.config import PLEX_TOKEN, PLEX_SERVER_URL, REQUEST_URL
from backend import auth_crypto, fsutil

log = logging.getLogger("plex-support.auth")
router = APIRouter(prefix="/api/auth")

COOKIE_NAME = "plex_support_sid"
SESSION_MAX_AGE = 86400  # 24 hours

# Server-side session store: session_id -> {uid, name, created_at}
_sessions: dict[str, dict] = {}

# User cache: plex_user_id -> {username, thumb, library_section_ids, is_admin, cached_at}
_user_cache: dict[int, dict] = {}
_admin_id: int = 0
CACHE_TTL = 300  # 5 minutes

# Persist sessions to disk so they survive restarts
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SESSIONS_FILE = DATA_DIR / "sessions.json"
USERS_FILE = DATA_DIR / "users.json"

_SECURE_COOKIE = PLEX_SERVER_URL.startswith("https") or os.environ.get("SECURE_COOKIE", "").lower() == "true"


def _load_sessions():
    if SESSIONS_FILE.exists():
        try:
            data = json.loads(SESSIONS_FILE.read_text())
            now = time.time()
            for sid, sess in data.items():
                if now - sess.get("created_at", 0) < SESSION_MAX_AGE:
                    _sessions[sid] = sess
        except Exception:
            pass


def _save_sessions():
    try:
        fsutil.write_private_text(SESSIONS_FILE, json.dumps(_sessions, indent=2))
    except Exception:
        pass


def _load_users():
    """Restore _user_cache from disk. Decrypts plex_token if present."""
    if not USERS_FILE.exists():
        return
    try:
        data = json.loads(USERS_FILE.read_text())
        for uid_str, info in data.items():
            enc = info.pop("plex_token_enc", "")
            if enc:
                info["plex_token"] = auth_crypto.decrypt(enc)
            else:
                info["plex_token"] = ""
            _user_cache[int(uid_str)] = info
    except Exception as e:
        log.warning(f"Failed to load users: {e}")


def _save_users():
    try:
        out: dict[str, dict] = {}
        for uid, info in _user_cache.items():
            persisted = {k: v for k, v in info.items() if k != "plex_token"}
            tok = info.get("plex_token") or ""
            if tok:
                persisted["plex_token_enc"] = auth_crypto.encrypt(tok)
            out[str(uid)] = persisted
        fsutil.write_private_text(USERS_FILE, json.dumps(out, indent=2))
    except Exception as e:
        log.warning(f"Failed to save users: {e}")


_load_sessions()
_load_users()


async def _plex_get(path: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(
            f"{PLEX_SERVER_URL}{path}",
            headers={"X-Plex-Token": token, "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def _get_admin_id() -> int:
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(
            "https://plex.tv/api/v2/user",
            headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json().get("id", 0)


async def _get_shared_users() -> dict[int, dict]:
    import xml.etree.ElementTree as ET

    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(
            "https://plex.tv/api/users",
            headers={"X-Plex-Token": PLEX_TOKEN},
        )
        resp.raise_for_status()

    users = {}
    root = ET.fromstring(resp.text)
    for user_el in root.findall(".//User"):
        uid = user_el.get("id")
        if not uid:
            continue
        has_library = any(
            int(srv.get("numLibraries", "0")) > 0
            for srv in user_el.findall(".//Server")
        )
        if not has_library:
            continue
        users[int(uid)] = {
            "username": user_el.get("username") or user_el.get("title", "Unknown"),
            "email": user_el.get("email", ""),
            "thumb": user_el.get("thumb", ""),
        }
    return users


async def _get_user_library_sections(user_token: str) -> list[int]:
    try:
        data = await _plex_get("/library/sections", user_token)
        sections = data.get("MediaContainer", {}).get("Directory", [])
        return [int(s["key"]) for s in sections if "key" in s]
    except Exception:
        return []


async def _get_user_info(plex_token: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(
                "https://plex.tv/api/v2/user",
                headers={"X-Plex-Token": plex_token, "Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


def _create_session(response: Response, user_id: int, username: str):
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = {
        "uid": user_id,
        "name": username,
        "created_at": time.time(),
    }
    _save_sessions()
    response.set_cookie(
        COOKIE_NAME, sid,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_SECURE_COOKIE,
    )


OLD_COOKIE = "plex_support_session"  # legacy signed cookie — clear on sight


def _destroy_session(request: Request, response: Response):
    sid = request.cookies.get(COOKIE_NAME)
    if sid and sid in _sessions:
        del _sessions[sid]
        _save_sessions()
    response.delete_cookie(COOKIE_NAME)
    response.delete_cookie(OLD_COOKIE)  # clean up legacy cookie


def get_current_user(request: Request) -> dict | None:
    sid = request.cookies.get(COOKIE_NAME)
    if not sid:
        return None
    sess = _sessions.get(sid)
    if not sess:
        return None
    if time.time() - sess.get("created_at", 0) > SESSION_MAX_AGE:
        del _sessions[sid]
        _save_sessions()
        return None
    return sess


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def get_user_sections(user_id: int) -> list[int]:
    """Section ids the user may touch. Callers treat [] as "no restriction",
    so an expired cache must never collapse to [] — that silently disables
    the access check for the rest of the session (sessions outlive the cache
    by ~24h vs 5min). On expiry, re-fetch with the user's own token; if that
    fails, enforce the last known list rather than nothing."""
    cached = _user_cache.get(user_id)
    if not cached:
        return []
    if time.time() - cached.get("cached_at", 0) < CACHE_TTL:
        return cached.get("library_section_ids", [])
    token = cached.get("plex_token", "")
    if token:
        sections = await _get_user_library_sections(token)
        if sections:
            cached["library_section_ids"] = sections
            cached["cached_at"] = time.time()
            return sections
    return cached.get("library_section_ids", [])


async def revalidate_users():
    """Re-check all cached users against Plex. Revoke sessions if removed."""
    try:
        shared = await _get_shared_users()
        shared_ids = set(shared.keys())
        for uid, data in list(_user_cache.items()):
            if data.get("is_admin"):
                continue
            if uid not in shared_ids:
                # Destroy all sessions for this user
                for sid, sess in list(_sessions.items()):
                    if sess.get("uid") == uid:
                        del _sessions[sid]
                _user_cache.pop(uid, None)
                log.info(f"Revoked user {data.get('username')} — no longer shared on Plex")
        _save_sessions()
        _save_users()
    except Exception as e:
        log.warning(f"User revalidation failed: {e}")


def revoke_user(user_id: int):
    """Admin-initiated revocation — destroys all sessions for this user."""
    for sid, sess in list(_sessions.items()):
        if sess.get("uid") == user_id:
            del _sessions[sid]
    _user_cache.pop(user_id, None)
    _save_sessions()
    _save_users()

    # Drop their device tokens as well, or a revoked user keeps getting push
    # notifications from fixes that were already in flight. Imported locally:
    # devices imports this module.
    try:
        from backend import devices
        devices.forget_user(user_id)
    except Exception as e:
        log.warning(f"Could not clear devices for revoked user {user_id}: {e}")


def cleanup_expired_sessions():
    """Remove expired sessions."""
    now = time.time()
    expired = [sid for sid, sess in _sessions.items() if now - sess.get("created_at", 0) > SESSION_MAX_AGE]
    for sid in expired:
        del _sessions[sid]
    if expired:
        _save_sessions()


@router.post("/plex")
async def login_with_plex(request: Request, response: Response):
    body = await request.json()
    plex_token = body.get("authToken", "")
    if not plex_token:
        raise HTTPException(400, "Missing authToken")

    user_info = await _get_user_info(plex_token)
    if not user_info:
        raise HTTPException(401, "Invalid Plex token")

    plex_user_id = user_info.get("id")
    plex_uuid = user_info.get("uuid", "")
    username = user_info.get("username") or user_info.get("title", "Unknown")

    admin_id = await _get_admin_id()
    is_admin = plex_user_id == admin_id

    shared_users = await _get_shared_users()
    if not is_admin and plex_user_id not in shared_users:
        raise HTTPException(403, "You don't have access to this Plex server")

    sections = await _get_user_library_sections(plex_token)

    global _admin_id
    if not _admin_id:
        _admin_id = admin_id

    # Preserve any existing fields (e.g. plex_token from prior login) when re-importing
    existing = _user_cache.get(plex_user_id, {})
    _user_cache[plex_user_id] = {
        **existing,
        "username": username,
        "thumb": user_info.get("thumb", ""),
        "library_section_ids": sections,
        "is_admin": is_admin,
        "cached_at": time.time(),
        "plex_token": plex_token,
        "plex_uuid": plex_uuid,
    }
    _save_users()

    # Kick off an initial cross-server watch-history sync (incremental on subsequent logins)
    import asyncio
    from backend import watch_data
    asyncio.create_task(watch_data.sync_user(plex_user_id, plex_token, plex_uuid))

    _create_session(response, plex_user_id, username)
    response.delete_cookie(OLD_COOKIE)  # clean up legacy cookie
    return {"username": username, "id": plex_user_id, "isAdmin": is_admin}


@router.get("/me")
async def me(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    uid = user["uid"]
    cached = _user_cache.get(uid)

    if not cached:
        global _admin_id
        if not _admin_id:
            _admin_id = await _get_admin_id()
        _user_cache[uid] = {
            "username": user["name"],
            "thumb": "",
            "library_section_ids": [],
            "is_admin": _admin_id > 0 and uid == _admin_id,
            "cached_at": time.time(),
        }
        cached = _user_cache[uid]

    return {
        "id": uid,
        "username": user["name"],
        "thumb": cached.get("thumb", ""),
        "library_section_ids": cached.get("library_section_ids", []),
        "isAdmin": cached.get("is_admin", False),
        "requestUrl": REQUEST_URL or None,
    }


async def _ensure_admin_id():
    global _admin_id
    if not _admin_id:
        _admin_id = await _get_admin_id()


def require_admin(request: Request) -> dict:
    user = require_user(request)
    cached = _user_cache.get(user["uid"], {})
    if not cached.get("is_admin"):
        raise HTTPException(403, "Admin access required")
    return user


def get_all_users() -> dict[int, dict]:
    return _user_cache


@router.get("/plex-users")
async def list_plex_users(request: Request):
    require_admin(request)
    shared = await _get_shared_users()
    result = []
    for uid, data in shared.items():
        imported = uid in _user_cache
        result.append({
            "id": uid,
            "username": data["username"],
            "thumb": data.get("thumb", ""),
            "imported": imported,
        })
    result.sort(key=lambda u: u["username"].lower())
    return result


@router.post("/import-users")
async def import_plex_users(request: Request):
    require_admin(request)
    body = await request.json()
    user_ids = body.get("userIds", [])
    if not user_ids:
        raise HTTPException(400, "No users selected")

    shared = await _get_shared_users()
    imported = []
    for uid in user_ids:
        if uid in _user_cache:
            continue
        user_data = shared.get(uid)
        if not user_data:
            continue
        _user_cache[uid] = {
            "username": user_data["username"],
            "thumb": user_data.get("thumb", ""),
            "library_section_ids": [],
            "is_admin": False,
            "cached_at": time.time(),
        }
        imported.append(user_data["username"])

    return {"imported": imported, "count": len(imported)}


@router.post("/logout")
async def logout(request: Request, response: Response):
    _destroy_session(request, response)
    return {"ok": True}
