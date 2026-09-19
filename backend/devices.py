"""Device tokens for push notifications.

One user has many devices. Tokens are stored per user in data/devices.json,
following the same on-disk pattern as sessions.json and users.json.
"""

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException

from backend import apns, fsutil
from backend.plex_auth import require_user

log = logging.getLogger("plex-support.devices")
router = APIRouter(prefix="/api/devices")

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DEVICES_FILE = DATA_DIR / "devices.json"

# user_id -> {device_token: registered_at}
_devices: dict[int, dict[str, float]] = {}


def _load():
    if not DEVICES_FILE.exists():
        return
    try:
        data = json.loads(DEVICES_FILE.read_text())
        for uid_str, tokens in data.items():
            _devices[int(uid_str)] = dict(tokens)
    except Exception as e:
        log.warning(f"Failed to load devices: {e}")


def _save():
    try:
        fsutil.write_private_text(
            DEVICES_FILE,
            json.dumps({str(uid): toks for uid, toks in _devices.items()}, indent=2),
        )
    except Exception as e:
        log.warning(f"Failed to save devices: {e}")


_load()


def _forget(token: str):
    """Drop a token from every user. Used when APNs says it is dead."""
    changed = False
    for uid in list(_devices):
        if token in _devices[uid]:
            del _devices[uid][token]
            if not _devices[uid]:
                del _devices[uid]
            changed = True
    if changed:
        _save()


def forget_user(user_id: int):
    """Drop every device belonging to a user — used when their access is revoked."""
    if _devices.pop(user_id, None) is not None:
        _save()


def tokens_for(user_id: int) -> list[str]:
    return list(_devices.get(user_id, {}).keys())


async def notify(user_id: int, title: str, body: str, data: dict | None = None):
    """Push to all of a user's devices. Safe to call when push is unconfigured."""
    if not apns.is_configured():
        return

    for token in tokens_for(user_id):
        result = await apns.send(token, title, body, data)
        if result == "gone":
            _forget(token)


@router.post("")
async def register_device(request: Request):
    user = require_user(request)
    body = await request.json()
    token = (body.get("token") or "").strip()

    if not token or len(token) > 200:
        raise HTTPException(400, "A device token is required")

    # A phone can change hands, or be signed into a different Plex account.
    # Claiming the token for this user first stops the previous owner's
    # notifications from landing on someone else's lock screen.
    _forget(token)

    _devices.setdefault(user["uid"], {})[token] = time.time()
    _save()
    return {"ok": True}


@router.delete("/{token}")
async def unregister_device(request: Request, token: str):
    user = require_user(request)
    user_tokens = _devices.get(user["uid"], {})
    if token in user_tokens:
        del user_tokens[token]
        if not user_tokens:
            del _devices[user["uid"]]
        _save()
    return {"ok": True}
