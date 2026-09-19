import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Request, HTTPException

import httpx

from backend import sonarr, radarr
from backend.plex_auth import require_user, get_all_users, get_user_sections
from backend.search import _item_accessible, _section_paths, _build_section_paths
from backend.rate_limit import check_rate_limit, record_request
from backend import history
from backend.config import (
    PLEX_TOKEN, PLEX_SERVER_URL,
    SONARR_URL, SONARR_API_KEY,
    RADARR_URL, RADARR_API_KEY,
)

log = logging.getLogger("plex-support.fix")
router = APIRouter(prefix="/api")


@dataclass
class FixRequest:
    id: str
    user_id: int
    username: str
    media_type: str  # "episode" or "movie"
    title: str
    status: str = "searching"  # searching, downloading, importing, done, available, stuck
    progress: float = 0
    stuck_reason: str = ""
    notified: bool = False
    created_at: float = field(default_factory=time.time)
    episode_id: int = 0
    movie_id: int = 0
    series_id: int = 0


# Global fix queue: fix_id -> FixRequest
_queue: dict[str, FixRequest] = {}


async def _wait_for_plex(fix: FixRequest):
    """Short wait after import — Sonarr/Radarr notify Plex automatically."""
    await asyncio.sleep(15)
    fix.status = "available"
    await _notify_available(fix)


async def _notify_available(fix: FixRequest):
    """Tell the user their media is playable again.

    Imported here rather than at module scope: devices imports plex_auth, and
    keeping the import local avoids tangling this module's import order.
    A push must never be able to disturb the fix that triggered it.
    """
    try:
        from backend import devices
        await devices.notify(
            fix.user_id,
            "Ready to watch",
            f"{fix.title} is back on Plex.",
            {"fixId": fix.id, "type": fix.media_type},
        )
    except Exception as e:
        log.warning(f"Push notification failed for {fix.id}: {e}")


def _format_rejections(files: list, status_msgs: list) -> str:
    """Build a human-readable reason from per-file rejections + queue statusMessages."""
    reasons: list[str] = []
    for f in files:
        for r in f.get("rejections", []):
            reason = r if isinstance(r, str) else r.get("reason", "")
            if reason:
                reasons.append(reason)
    for m in status_msgs:
        for msg in (m.get("messages") or []):
            if msg:
                reasons.append(msg)
    seen: set[str] = set()
    deduped: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return "; ".join(deduped[:3])


async def _poll_episode(fix: FixRequest):
    try:
        warning_strikes = 0     # consecutive cycles in queue-warning state
        last_msgs: list = []
        # Decypharr force-imports stuck downloads itself, so we only observe here:
        # a queue warning means "still assembling / Sonarr will retry", and we wait
        # out the window before declaring stuck.
        TOTAL_CYCLES = 120      # ~20 minutes
        for _ in range(TOTAL_CYCLES):
            await asyncio.sleep(10)

            ep = await sonarr.get(f"/episode/{fix.episode_id}")
            if ep.get("hasFile"):
                fix.status = "done"
                fix.progress = 100
                await _wait_for_plex(fix)
                return

            q = await sonarr.queue()
            records = q.get("records", []) if isinstance(q, dict) else []

            matched = next((it for it in records if it.get("episodeId") == fix.episode_id), None)
            if matched is None:
                # Not in queue yet (still searching) or just left it (mid-import).
                continue

            dl_status = matched.get("trackedDownloadStatus", "")
            dl_state = matched.get("trackedDownloadState", "")
            is_warning = dl_status == "warning" or dl_state in ("importBlocked", "failedPending")

            if not is_warning:
                warning_strikes = 0
                size = matched.get("size", 1)
                sizeleft = matched.get("sizeleft", 0)
                fix.progress = max(0, min(100, ((size - sizeleft) / size) * 100)) if size else 0
                fix.status = "downloading"
                continue

            warning_strikes += 1
            msgs = matched.get("statusMessages", [])
            if msgs:
                last_msgs = msgs

            # Warning state — the download is present but not imported yet.
            # Decypharr handles the force import; just report progress and wait.
            fix.status = "importing"

        # Loop exhausted without resolution
        if warning_strikes > 0:
            fix.status = "stuck"
            fix.stuck_reason = _format_rejections([], last_msgs) or "Import did not complete after 20 minutes"
        elif fix.status == "downloading":
            fix.status = "stuck"
            fix.stuck_reason = "Download did not complete after 20 minutes"
        else:
            fix.status = "stuck"
            fix.stuck_reason = "Not found after 20 minutes"
    except Exception as e:
        log.warning(f"Poll episode failed: {e}")
        fix.status = "stuck"
        fix.stuck_reason = "An error occurred while tracking this fix"


async def _poll_movie(fix: FixRequest):
    try:
        warning_strikes = 0
        last_msgs: list = []
        TOTAL_CYCLES = 120
        for _ in range(TOTAL_CYCLES):
            await asyncio.sleep(10)

            m = await radarr.movie(fix.movie_id)
            if m.get("hasFile"):
                fix.status = "done"
                fix.progress = 100
                await _wait_for_plex(fix)
                return

            q = await radarr.queue()
            records = q.get("records", []) if isinstance(q, dict) else []

            matched = next((it for it in records if it.get("movieId") == fix.movie_id), None)
            if matched is None:
                continue

            dl_status = matched.get("trackedDownloadStatus", "")
            dl_state = matched.get("trackedDownloadState", "")
            is_warning = dl_status == "warning" or dl_state in ("importBlocked", "failedPending")

            if not is_warning:
                warning_strikes = 0
                size = matched.get("size", 1)
                sizeleft = matched.get("sizeleft", 0)
                fix.progress = max(0, min(100, ((size - sizeleft) / size) * 100)) if size else 0
                fix.status = "downloading"
                continue

            warning_strikes += 1
            msgs = matched.get("statusMessages", [])
            if msgs:
                last_msgs = msgs

            # Decypharr handles the force import — observe only.
            fix.status = "importing"

        if warning_strikes > 0:
            fix.status = "stuck"
            fix.stuck_reason = _format_rejections([], last_msgs) or "Import did not complete after 20 minutes"
        elif fix.status == "downloading":
            fix.status = "stuck"
            fix.stuck_reason = "Download did not complete after 20 minutes"
        else:
            fix.status = "stuck"
            fix.stuck_reason = "Not found after 20 minutes"
    except Exception as e:
        log.warning(f"Poll movie failed: {e}")
        fix.status = "stuck"
        fix.stuck_reason = "An error occurred while tracking this fix"


def _is_already_fixing(media_type: str, episode_id: int = 0, movie_id: int = 0) -> bool:
    """Check if there's already an active fix for this item."""
    for f in _queue.values():
        if f.status in ("done", "available"):
            continue
        if media_type == "episode" and f.episode_id == episode_id:
            return True
        if media_type == "movie" and f.movie_id == movie_id:
            return True
    return False


@router.post("/fix")
async def fix_media(request: Request):
    user = require_user(request)
    body = await request.json()

    media_type = body.get("type")  # "episode" or "movie"
    if media_type not in ("episode", "movie"):
        raise HTTPException(400, "type must be 'episode' or 'movie'")

    is_admin = get_all_users().get(user["uid"], {}).get("is_admin", False)
    if not is_admin:
        limit_error = check_rate_limit(user["uid"])
        if limit_error:
            raise HTTPException(429, limit_error)

    fix_id = f"{user['uid']}-{int(time.time() * 1000)}"

    if media_type == "episode":
        episode_id = body.get("episodeId")
        file_id = body.get("fileId")
        series_id = body.get("seriesId")
        title = body.get("title", "Unknown")
        if not all([episode_id, series_id]):
            raise HTTPException(400, "episodeId and seriesId required")

        if _is_already_fixing("episode", episode_id=episode_id):
            raise HTTPException(409, "This episode is already being fixed")

        # Verify user has access to this content
        if not is_admin:
            if not _section_paths:
                await _build_section_paths()
            sections = await get_user_sections(user["uid"])
            series_data = await sonarr.get(f"/series/{series_id}")
            if sections and not _item_accessible(series_data.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")

        if file_id:
            await sonarr.delete_episode_file(file_id)

        # Blocklist the current release (if we can find it in history) so the
        # next search picks a different one. fail_history only auto-triggers a
        # re-search when the download is still in queue — for already-imported
        # files it just blocklists. Always trigger an explicit search after.
        try:
            hist = await sonarr.history_for_episode(episode_id)
            recs = hist.get("records", []) if isinstance(hist, dict) else (hist or [])
            grabbed = next((r for r in recs if r.get("eventType") == "grabbed"), None)
            if grabbed and grabbed.get("id"):
                await sonarr.fail_history(grabbed["id"])
        except Exception as e:
            log.warning(f"Blocklist via history failed for episode {episode_id}: {e}")

        await sonarr.search_episode(episode_id)

        fix = FixRequest(
            id=fix_id, user_id=user["uid"], username=user["name"],
            media_type="episode", title=title,
            episode_id=episode_id, series_id=series_id,
        )
    else:
        movie_id = body.get("movieId")
        file_id = body.get("fileId")
        title = body.get("title", "Unknown")
        if not movie_id:
            raise HTTPException(400, "movieId required")

        if _is_already_fixing("movie", movie_id=movie_id):
            raise HTTPException(409, "This movie is already being fixed")

        # Verify user has access to this content
        if not is_admin:
            if not _section_paths:
                await _build_section_paths()
            sections = await get_user_sections(user["uid"])
            movie_data = await radarr.movie(movie_id)
            if sections and not _item_accessible(movie_data.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")

        if file_id:
            await radarr.delete_movie_file(file_id)

        try:
            hist = await radarr.history_for_movie(movie_id)
            recs = hist.get("records", []) if isinstance(hist, dict) else (hist or [])
            grabbed = next((r for r in recs if r.get("eventType") == "grabbed"), None)
            if grabbed and grabbed.get("id"):
                await radarr.fail_history(grabbed["id"])
        except Exception as e:
            log.warning(f"Blocklist via history failed for movie {movie_id}: {e}")

        await radarr.search_movie(movie_id)

        fix = FixRequest(
            id=fix_id, user_id=user["uid"], username=user["name"],
            media_type="movie", title=title, movie_id=movie_id,
        )

    _queue[fix_id] = fix
    if not is_admin:
        record_request(user["uid"])
    history.record(
        user_id=user["uid"], username=user["name"],
        media_type=media_type, title=fix.title,
        episode_id=fix.episode_id, movie_id=fix.movie_id,
    )

    if media_type == "episode":
        asyncio.create_task(_poll_episode(fix))
    else:
        asyncio.create_task(_poll_movie(fix))

    return {"fixId": fix_id, "status": "searching"}


@router.get("/queue")
async def get_queue(request: Request):
    user = require_user(request)
    user_fixes = [
        {
            "id": f.id,
            "title": f.title,
            "type": f.media_type,
            "status": f.status,
            "progress": round(f.progress, 1),
            "stuckReason": f.stuck_reason,
            "notified": f.notified,
            "createdAt": f.created_at,
            "episodeId": f.episode_id,
            "movieId": f.movie_id,
        }
        for f in _queue.values()
        if f.user_id == user["uid"]
    ]
    # Newest first, keep last 20
    user_fixes.sort(key=lambda x: x["createdAt"], reverse=True)
    return user_fixes[:20]


@router.delete("/queue/{fix_id}")
async def remove_queue_item(request: Request, fix_id: str):
    user = require_user(request)
    fix = _queue.get(fix_id)
    if not fix:
        raise HTTPException(404, "Not found")
    if fix.user_id != user["uid"]:
        raise HTTPException(403, "Not your fix request")
    del _queue[fix_id]
    return {"ok": True}


@router.delete("/queue")
async def clear_queue(request: Request):
    user = require_user(request)
    to_remove = [fid for fid, f in _queue.items() if f.user_id == user["uid"]]
    for fid in to_remove:
        del _queue[fid]
    return {"ok": True, "removed": len(to_remove)}


def get_fix(fix_id: str) -> FixRequest | None:
    return _queue.get(fix_id)


def mark_notified(fix_id: str):
    fix = _queue.get(fix_id)
    if fix:
        fix.notified = True


# ---------------------------------------------------------------------------
# Interactive fix helpers & endpoints
# ---------------------------------------------------------------------------

def _release_group(title: str) -> str:
    """Extract release group from title (last segment after final '-')."""
    if "-" in title:
        return title.rsplit("-", 1)[-1].strip().lower()
    return ""


def _has_language(langs: list, target: str) -> bool:
    for lang in langs:
        name = lang.get("name", "") if isinstance(lang, dict) else str(lang)
        if name.lower() == target:
            return True
    return not langs  # no language info = assume match


def _transform_releases(raw: list, blocklisted_title: str, original_language: str = "english") -> list[dict]:
    blocked_group = _release_group(blocklisted_title)
    releases = []
    for r in raw:
        title = r.get("title", "")
        rejected = bool(r.get("rejected", False))
        if blocklisted_title and title == blocklisted_title:
            continue
        quality_name = r.get("quality", {}).get("quality", {}).get("name", "")
        if "br-disk" in quality_name.lower() or "raw-hd" in quality_name.lower():
            continue
        releases.append({
            "guid": r.get("guid", ""),
            "indexerId": r.get("indexerId", 0),
            "title": title,
            "quality": r.get("quality", {}).get("quality", {}).get("name", "Unknown"),
            "qualityWeight": r.get("qualityWeight", 0),
            "size": r.get("size", 0),
            "sizeGB": f"{r.get('size', 0) / 1073741824:.1f}",
            "protocol": r.get("protocol", "unknown"),
            "indexer": r.get("indexer", "Unknown"),
            "seeders": r.get("seeders"),
            "age": r.get("age", 0),
            "rejected": rejected,
            "rejections": [rej if isinstance(rej, str) else rej.get("reason", "") for rej in r.get("rejections", [])],
            "recommended": False,
            "_has_lang": _has_language(r.get("languages", []), original_language),
        })
    # Sort: approved first, usenet before torrent, then by quality weight desc
    releases.sort(key=lambda x: (x["rejected"], x["protocol"] != "usenet", -x["qualityWeight"]))
    # Mark first release in the original language from a different release group
    for rel in releases:
        group = _release_group(rel["title"])
        if (not blocked_group or group != blocked_group) and rel["_has_lang"]:
            rel["recommended"] = True
            break
    # Remove internal field
    for rel in releases:
        del rel["_has_lang"]
    return releases


@router.get("/fix/check-repeat")
async def check_repeat(request: Request, type: str, episodeId: int = 0, movieId: int = 0):
    user = require_user(request)
    repeat = history.was_fixed_today(user["uid"], type, episode_id=episodeId, movie_id=movieId)
    return {"repeat": repeat}


@router.post("/fix/search-releases")
async def search_releases(request: Request):
    """Non-destructive: just looks up current release name and fetches available releases.
    No file deletion or rate limit consumed — that happens in /fix/grab."""
    user = require_user(request)
    body = await request.json()

    media_type = body.get("type")
    if media_type not in ("episode", "movie"):
        raise HTTPException(400, "type must be 'episode' or 'movie'")

    is_admin = get_all_users().get(user["uid"], {}).get("is_admin", False)

    blocklisted_title = ""
    original_language = "english"

    if media_type == "episode":
        episode_id = body.get("episodeId")
        file_id = body.get("fileId")
        series_id = body.get("seriesId")
        if not all([episode_id, file_id, series_id]):
            raise HTTPException(400, "episodeId, fileId, and seriesId required")

        if _is_already_fixing("episode", episode_id=episode_id):
            raise HTTPException(409, "This episode is already being fixed")

        # Access check
        if not is_admin:
            if not _section_paths:
                await _build_section_paths()
            sections = await get_user_sections(user["uid"])
            series_data = await sonarr.get(f"/series/{series_id}")
            if sections and not _item_accessible(series_data.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")

        # Find the current release title so we can filter it from results
        # Best source: the actual file on disk has sceneName/releaseGroup
        if file_id:
            try:
                file_info = await sonarr.episode_file(file_id)
                blocklisted_title = file_info.get("sceneName", "") or file_info.get("originalFilePath", "")
            except Exception:
                pass

        # Fallback: check queue or history
        if not blocklisted_title:
            q = await sonarr.queue()
            records = q.get("records", []) if isinstance(q, dict) else []
            for item in records:
                if item.get("episodeId") == episode_id:
                    blocklisted_title = item.get("title", "")
                    break

        # Get original language for recommendation
        series_data = await sonarr.get(f"/series/{series_id}")
        original_language = series_data.get("originalLanguage", {}).get("name", "English").lower()

        # Search releases — no destructive actions yet, user picks first
        raw_releases = await sonarr.search_releases(episode_id)

    else:
        movie_id = body.get("movieId")
        file_id = body.get("fileId")
        if not all([movie_id, file_id]):
            raise HTTPException(400, "movieId and fileId required")

        if _is_already_fixing("movie", movie_id=movie_id):
            raise HTTPException(409, "This movie is already being fixed")

        # Access check
        if not is_admin:
            if not _section_paths:
                await _build_section_paths()
            sections = await get_user_sections(user["uid"])
            movie_data = await radarr.movie(movie_id)
            if sections and not _item_accessible(movie_data.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")

        # Find the current release title so we can filter it from results
        if file_id:
            try:
                file_info = await radarr.movie_file(file_id)
                blocklisted_title = file_info.get("sceneName", "") or file_info.get("originalFilePath", "")
            except Exception:
                pass

        if not blocklisted_title:
            q = await radarr.queue()
            records = q.get("records", []) if isinstance(q, dict) else []
            for item in records:
                if item.get("movieId") == movie_id:
                    blocklisted_title = item.get("title", "")
                    break

        # Get original language for recommendation
        movie_data = await radarr.movie(movie_id)
        original_language = movie_data.get("originalLanguage", {}).get("name", "English").lower()

        # Search releases — no destructive actions yet, user picks first
        raw_releases = await radarr.search_releases(movie_id)

    releases = _transform_releases(
        raw_releases if isinstance(raw_releases, list) else [],
        blocklisted_title,
        original_language,
    )
    return {"blocklisted": blocklisted_title, "releases": releases}


@router.post("/fix/grab")
async def grab_release(request: Request):
    """Destructive: deletes file, blocklists queue item, grabs chosen release."""
    user = require_user(request)
    body = await request.json()

    media_type = body.get("type")
    if media_type not in ("episode", "movie"):
        raise HTTPException(400, "type must be 'episode' or 'movie'")

    guid = body.get("guid")
    indexer_id = body.get("indexerId")
    title = body.get("title", "Unknown")
    if not guid or not indexer_id:
        raise HTTPException(400, "guid and indexerId required")

    is_admin = get_all_users().get(user["uid"], {}).get("is_admin", False)
    if not is_admin:
        limit_error = check_rate_limit(user["uid"])
        if limit_error:
            raise HTTPException(429, limit_error)

    fix_id = f"{user['uid']}-{int(time.time() * 1000)}"

    if media_type == "episode":
        episode_id = body.get("episodeId")
        series_id = body.get("seriesId")
        file_id = body.get("fileId")
        if not all([episode_id, series_id]):
            raise HTTPException(400, "episodeId and seriesId required")

        # Access check
        if not is_admin:
            if not _section_paths:
                await _build_section_paths()
            sections = await get_user_sections(user["uid"])
            series_data = await sonarr.get(f"/series/{series_id}")
            if sections and not _item_accessible(series_data.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")

        # Remove from queue if downloading, delete file, then grab chosen release
        q = await sonarr.queue()
        records = q.get("records", []) if isinstance(q, dict) else []
        for item in records:
            if item.get("episodeId") == episode_id:
                async with httpx.AsyncClient(timeout=30) as c:
                    resp = await c.delete(
                        f"{SONARR_URL}/api/v3/queue/{item['id']}",
                        headers={"X-Api-Key": SONARR_API_KEY},
                        params={"removeFromClient": "true", "blocklist": "true"},
                    )
                    resp.raise_for_status()
                break

        if file_id:
            try:
                await sonarr.delete_episode_file(file_id)
            except Exception:
                pass

        await sonarr.grab_release(guid, indexer_id)

        fix = FixRequest(
            id=fix_id, user_id=user["uid"], username=user["name"],
            media_type="episode", title=title,
            episode_id=episode_id, series_id=series_id,
        )
        _queue[fix_id] = fix
        asyncio.create_task(_poll_episode(fix))

    else:
        movie_id = body.get("movieId")
        file_id = body.get("fileId")
        if not movie_id:
            raise HTTPException(400, "movieId required")

        # Access check
        if not is_admin:
            if not _section_paths:
                await _build_section_paths()
            sections = await get_user_sections(user["uid"])
            movie_data = await radarr.movie(movie_id)
            if sections and not _item_accessible(movie_data.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")

        # Remove from queue if downloading, delete file, then grab chosen release
        q = await radarr.queue()
        records = q.get("records", []) if isinstance(q, dict) else []
        for item in records:
            if item.get("movieId") == movie_id:
                async with httpx.AsyncClient(timeout=30) as c:
                    resp = await c.delete(
                        f"{RADARR_URL}/api/v3/queue/{item['id']}",
                        headers={"X-Api-Key": RADARR_API_KEY},
                        params={"removeFromClient": "true", "blocklist": "true"},
                    )
                    resp.raise_for_status()
                break

        if file_id:
            try:
                await radarr.delete_movie_file(file_id)
            except Exception:
                pass

        await radarr.grab_release(guid, indexer_id)

        fix = FixRequest(
            id=fix_id, user_id=user["uid"], username=user["name"],
            media_type="movie", title=title, movie_id=movie_id,
        )
        _queue[fix_id] = fix
        asyncio.create_task(_poll_movie(fix))

    if not is_admin:
        record_request(user["uid"])
    history.record(
        user_id=user["uid"], username=user["name"],
        media_type=media_type, title=title,
        episode_id=body.get("episodeId", 0),
        movie_id=body.get("movieId", 0),
    )

    return {"fixId": fix_id, "status": "searching"}
