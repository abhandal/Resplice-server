import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

load_dotenv()

# Rolling log file under the bind-mounted data dir so logs survive container
# restarts. 5 MB per file × 5 backups ≈ 25 MB on disk max.
LOG_DIR = Path(__file__).parent.parent / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
_log_format = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

_file_handler = RotatingFileHandler(
    LOG_DIR / "plex-support.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(_log_format)

_stderr_handler = logging.StreamHandler(sys.stderr)
_stderr_handler.setFormatter(_log_format)

logging.basicConfig(level=logging.INFO, handlers=[_stderr_handler, _file_handler], force=True)

app = FastAPI(title="Plex Support")

from backend.plex_auth import router as auth_router  # noqa: E402
from backend.search import router as search_router  # noqa: E402
from backend.fix import router as fix_router  # noqa: E402
from backend.discord import router as discord_router  # noqa: E402
from backend.stats import router as stats_router  # noqa: E402
from backend.devices import router as devices_router  # noqa: E402
from backend.rate_limit import get_rate_info, set_user_limits  # noqa: E402
from backend.plex_auth import require_user, require_admin, get_all_users  # noqa: E402
from backend import history  # noqa: E402

app.include_router(auth_router)
app.include_router(search_router)
app.include_router(fix_router)
app.include_router(discord_router)
app.include_router(stats_router)
app.include_router(devices_router)

from backend.search import refresh_library_cache  # noqa: E402


from backend.plex_auth import _ensure_admin_id, revalidate_users, revoke_user, cleanup_expired_sessions, _get_shared_users  # noqa: E402


@app.on_event("startup")
async def startup():
    await _ensure_admin_id()
    await refresh_library_cache()

    # Pick up fixes that were still running when the server last stopped, so a
    # restart mid-download doesn't leave the user waiting for a push that can
    # no longer fire.
    from backend.fix import resume_queue
    await resume_queue()

    async def _refresh_loop():
        while True:
            await asyncio.sleep(300)  # 5 minutes
            await refresh_library_cache()
            await revalidate_users()
            cleanup_expired_sessions()

    async def _watch_history_loop():
        from backend import watch_data
        # Stagger initial run so the app is fully up first
        await asyncio.sleep(30)
        while True:
            users = list(get_all_users().items())
            for uid, info in users:
                token = info.get("plex_token") or ""
                uuid = info.get("plex_uuid") or ""
                if not token or not uuid:
                    continue
                try:
                    await watch_data.sync_user(uid, token, uuid)
                except Exception as e:
                    import logging
                    logging.getLogger("plex-support").warning(f"watch_data sync error for {uid}: {e}")
            await asyncio.sleep(watch_data.REFRESH_INTERVAL)

    asyncio.create_task(_refresh_loop())
    asyncio.create_task(_watch_history_loop())


@app.get("/api/health")
async def health():
    """Also serves as discovery for native clients.

    The iOS app asks the user for a server address, and needs to tell a real
    plex-support server from any URL that happens to answer 200. `product` is
    what it matches on; `push` tells it whether to bother asking for
    notification permission.
    """
    from backend import apns
    return {
        "status": "ok",
        "product": "plex-support",
        "apiVersion": 1,
        "push": apns.is_configured(),
    }


@app.get("/api/plex-status")
async def plex_status(request: Request):
    require_user(request)
    from backend.config import PLEX_SERVER_URL, PLEX_TOKEN
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            resp = await c.get(
                f"{PLEX_SERVER_URL}/",
                headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
            )
            resp.raise_for_status()
            return {"online": True}
    except Exception:
        return {"online": False}


@app.get("/api/rate-limit")
async def rate_limit_info(request: Request):
    user = require_user(request)
    is_admin = get_all_users().get(user["uid"], {}).get("is_admin", False)
    if is_admin:
        return {"remaining": -1, "maxPerDay": -1, "cooldownLeft": 0}
    return get_rate_info(user["uid"])


@app.get("/api/admin/users")
async def admin_users(request: Request):
    require_admin(request)
    cached = get_all_users()

    # Pull canonical user list from Plex so admins can manage limits for every
    # shared user, not just those whose session is currently in the in-memory
    # cache. Falls back to cache-only if Plex is unreachable.
    try:
        shared = await _get_shared_users()
    except Exception:
        shared = {}

    result = []
    seen: set[int] = set()
    for uid, data in shared.items():
        cached_data = cached.get(uid, {})
        is_admin = cached_data.get("is_admin", False)
        rate = {"remaining": -1, "maxPerDay": -1, "cooldownLeft": 0} if is_admin else get_rate_info(uid)
        result.append({
            "id": uid,
            "username": cached_data.get("username") or data.get("username", "Unknown"),
            "thumb": cached_data.get("thumb") or data.get("thumb", ""),
            "isAdmin": is_admin,
            "rateLimit": rate,
        })
        seen.add(uid)

    # Admin (and any cached non-shared user) — Plex's shared-users endpoint
    # doesn't include the server owner, so pick them up from the cache.
    for uid, data in cached.items():
        if uid in seen:
            continue
        is_admin = data.get("is_admin", False)
        rate = {"remaining": -1, "maxPerDay": -1, "cooldownLeft": 0} if is_admin else get_rate_info(uid)
        result.append({
            "id": uid,
            "username": data.get("username", "Unknown"),
            "thumb": data.get("thumb", ""),
            "isAdmin": is_admin,
            "rateLimit": rate,
        })

    result.sort(key=lambda u: u["username"].lower())
    return result


@app.put("/api/admin/users/{user_id}/limits")
async def update_user_limits(request: Request, user_id: int):
    require_admin(request)
    body = await request.json()
    max_per_day = body.get("maxPerDay", 10)
    cooldown = body.get("cooldown", 60)
    if not isinstance(max_per_day, int) or max_per_day < 1 or max_per_day > 100:
        raise HTTPException(422, "maxPerDay must be between 1 and 100")
    if not isinstance(cooldown, (int, float)) or cooldown < 0 or cooldown > 3600:
        raise HTTPException(422, "cooldown must be between 0 and 3600 seconds")
    set_user_limits(user_id, max_per_day, int(cooldown))
    return {"ok": True}


@app.post("/api/admin/users/{user_id}/revoke")
async def admin_revoke_user(request: Request, user_id: int):
    require_admin(request)
    revoke_user(user_id)
    return {"ok": True}


@app.get("/api/admin/history")
async def admin_history(request: Request):
    require_admin(request)
    return history.get_all(200)


@app.post("/api/admin/scan")
async def admin_scan_folder(request: Request):
    """Trigger a Plex scan for a specific folder path. Admin only."""
    from urllib.parse import quote
    from backend.config import PLEX_SERVER_URL, PLEX_TOKEN
    from backend import sonarr, radarr

    require_admin(request)
    body = await request.json()
    scan_type = body.get("type")  # "season" or "movie"

    if scan_type == "season":
        series_id = body.get("seriesId")
        season_number = body.get("seasonNumber")
        if not series_id or season_number is None:
            raise HTTPException(400, "seriesId and seasonNumber required")

        # Get actual season folder path from episode files instead of guessing the name
        ep_files = await sonarr.get("/episodefile", {"seriesId": series_id})
        season_path = None
        for f in ep_files:
            if f.get("seasonNumber") == season_number:
                from pathlib import Path as P
                season_path = str(P(f["path"]).parent)
                break

        if not season_path:
            # Fallback: construct from series path (try without zero-padding first)
            series_data = await sonarr.get(f"/series/{series_id}")
            root = series_data.get("path", "")
            season_path = f"{root}/Season {season_number}" if season_number > 0 else f"{root}/Specials"

        scan_path = season_path

    elif scan_type == "movie":
        movie_id = body.get("movieId")
        if not movie_id:
            raise HTTPException(400, "movieId required")

        movie_data = await radarr.movie(movie_id)
        scan_path = movie_data.get("path", "")

    else:
        raise HTTPException(400, "type must be 'season' or 'movie'")

    if not scan_path:
        raise HTTPException(404, "Could not determine folder path")

    # Find the Plex library section for this path
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(
            f"{PLEX_SERVER_URL}/library/sections",
            headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
        )
        resp.raise_for_status()
        sections = resp.json().get("MediaContainer", {}).get("Directory", [])

    section_id = None
    for sec in sections:
        for loc in sec.get("Location", []):
            if scan_path.startswith(loc.get("path", "")):
                section_id = sec.get("key")
                break
        if section_id:
            break

    if not section_id:
        raise HTTPException(404, f"No Plex library section found for path: {scan_path}")

    # Trigger the scan
    encoded = quote(scan_path)
    async with httpx.AsyncClient(timeout=10) as c:
        resp = await c.get(
            f"{PLEX_SERVER_URL}/library/sections/{section_id}/refresh?path={encoded}",
            headers={"X-Plex-Token": PLEX_TOKEN},
        )
        resp.raise_for_status()

    return {"ok": True, "path": scan_path}


# Serve React static files with SPA fallback
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = (static_dir / full_path).resolve()
        if file_path.is_relative_to(static_dir.resolve()) and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(static_dir / "index.html")
