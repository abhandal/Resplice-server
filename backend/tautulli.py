"""Tautulli helpers — per-user watched state for episodes and movies."""

import logging
import time

import httpx

from backend.config import TAUTULLI_URL, TAUTULLI_API_KEY

log = logging.getLogger("plex-support.tautulli")

# Threshold above which Tautulli's watched_status (0..1) counts as "watched"
WATCHED_THRESHOLD = 0.9
# Cache: user_id -> (cached_at, set of (lower_title, year))
_movie_cache: dict[int, tuple[float, set[tuple[str, int]]]] = {}
# Cache: (user_id, section_id) -> (cached_at, set of grandparent rating_keys started)
_started_shows_cache: dict[tuple[int, int], tuple[float, set[int]]] = {}
MOVIE_CACHE_TTL = 300  # 5 minutes
STARTED_SHOWS_CACHE_TTL = 300


def is_configured() -> bool:
    return bool(TAUTULLI_URL and TAUTULLI_API_KEY)


async def _call(cmd: str, params: dict | None = None) -> dict:
    if not is_configured():
        return {}
    full = {"apikey": TAUTULLI_API_KEY, "cmd": cmd, **(params or {})}
    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.get(f"{TAUTULLI_URL}/api/v2", params=full)
        resp.raise_for_status()
        return resp.json().get("response", {}).get("data", {}) or {}


async def watched_episodes(user_id: int, show_rating_key: int) -> set[tuple[int, int]]:
    """Return set of (season, episode) tuples the user has fully watched for this show."""
    try:
        data = await _call("get_history", {
            "user_id": user_id,
            "grandparent_rating_key": show_rating_key,
            "length": 2000,
        })
    except Exception as e:
        log.warning(f"Tautulli watched_episodes failed: {e}")
        return set()

    watched: set[tuple[int, int]] = set()
    for h in data.get("data", []):
        if h.get("media_type") != "episode":
            continue
        if (h.get("watched_status") or 0) < WATCHED_THRESHOLD:
            continue
        season = h.get("parent_media_index")
        episode = h.get("media_index")
        if season is not None and episode is not None:
            watched.add((int(season), int(episode)))
    return watched


async def is_movie_watched(user_id: int, movie_rating_key: int) -> bool:
    try:
        data = await _call("get_history", {
            "user_id": user_id,
            "rating_key": movie_rating_key,
            "length": 10,
        })
    except Exception as e:
        log.warning(f"Tautulli is_movie_watched failed: {e}")
        return False

    for h in data.get("data", []):
        if h.get("media_type") != "movie":
            continue
        if (h.get("watched_status") or 0) >= WATCHED_THRESHOLD:
            return True
    return False


async def user_summary(user_id: int) -> dict:
    """Per-user totals across canonical periods (30d, 90d, YTD, all-time).

    Returns: {"period_key": {"seconds": int, "plays": int}, ...}
    """
    from datetime import datetime
    today = datetime.now()
    ytd_days = (today - datetime(today.year, 1, 1)).days + 1

    try:
        data = await _call("get_user_watch_time_stats", {
            "user_id": user_id,
            "query_days": f"30,90,{ytd_days},0",
        })
    except Exception as e:
        log.warning(f"Tautulli user_summary failed: {e}")
        return {}

    rows = data if isinstance(data, list) else data.get("data", [])
    by_days = {int(r.get("query_days") or 0): r for r in rows}

    def pluck(days: int) -> dict:
        r = by_days.get(days, {})
        return {"seconds": int(r.get("total_time") or 0), "plays": int(r.get("total_plays") or 0)}

    return {
        "30days": pluck(30),
        "90days": pluck(90),
        "ytd": pluck(ytd_days),
        "allTime": pluck(0),
    }


async def user_library_breakdown(user_id: int, time_range_days: int) -> list[dict]:
    """Per-library plays/seconds for the given window. Single get_home_stats call;
    we only pull the `top_libraries` section from the response."""
    effective_range = time_range_days if time_range_days > 0 else 36500
    try:
        data = await _call("get_home_stats", {
            "user_id": user_id,
            "time_range": effective_range,
            "stats_count": 20,
        })
    except Exception as e:
        log.warning(f"Tautulli user_library_breakdown failed: {e}")
        return []

    sections = data if isinstance(data, list) else []
    by_id = {s.get("stat_id"): s.get("rows", []) for s in sections}
    out = []
    other_seconds = 0
    other_plays = 0
    for r in by_id.get("top_libraries", []):
        name = r.get("section_name")
        plays = int(r.get("total_plays") or 0)
        secs = int(r.get("total_duration") or 0)
        if not name:
            # Roll up rows from deleted Plex libraries (Tautulli kept the history)
            other_seconds += secs
            other_plays += plays
            continue
        out.append({
            "library": name,
            "sectionId": r.get("section_id"),
            "type": r.get("section_type", ""),
            "plays": plays,
            "seconds": secs,
        })
    if other_seconds > 0:
        out.append({
            "library": "Other",
            "sectionId": 0,
            "type": "",
            "plays": other_plays,
            "seconds": other_seconds,
        })
    return out


async def user_breakdown(user_id: int, time_range_days: int = 30, count: int = 10) -> dict:
    """Top shows / movies / platforms for the user over time_range_days. Single call.

    Tautulli's get_home_stats treats time_range=0 as "no range / no results" rather
    than "all time", so we substitute a sentinel large value to capture everything.
    """
    effective_range = time_range_days if time_range_days > 0 else 36500
    try:
        data = await _call("get_home_stats", {
            "user_id": user_id,
            "time_range": effective_range,
            "stats_count": count,
        })
    except Exception as e:
        log.warning(f"Tautulli user_breakdown failed: {e}")
        return {"topShows": [], "topMovies": [], "topPlatforms": []}

    sections = data if isinstance(data, list) else []
    by_id: dict[str, list] = {sec.get("stat_id"): sec.get("rows", []) for sec in sections}

    def media_rows(stat_id: str) -> list[dict]:
        out = []
        for r in by_id.get(stat_id, []):
            out.append({
                "title": r.get("title") or "",
                "year": r.get("year"),
                "plays": int(r.get("total_plays") or 0),
                "seconds": int(r.get("total_duration") or 0),
                "ratingKey": r.get("rating_key") or r.get("grandparent_rating_key"),
                "thumb": r.get("thumb") or r.get("grandparent_thumb") or "",
            })
        return out

    def platform_rows() -> list[dict]:
        out = []
        for r in by_id.get("top_platforms", []):
            # Tautulli's top_platforms: `platform` = friendly name ("Android"/"tvOS"),
            # `platform_name` = short code ("android"/"atv"). Prefer the friendly one.
            out.append({
                "platform": r.get("platform") or r.get("platform_name") or "Unknown",
                "plays": int(r.get("total_plays") or 0),
                "seconds": int(r.get("total_duration") or 0),
            })
        return out

    return {
        "topShows": media_rows("top_tv"),
        "topMovies": media_rows("top_movies"),
        "topPlatforms": platform_rows(),
    }


async def started_shows_in_section(user_id: int, section_id: int) -> set[int]:
    """Set of distinct grandparent_rating_keys (= shows) the user has watched at least
    one episode of, scoped to a Plex library section. Cached per (user, section)."""
    key = (user_id, section_id)
    cached = _started_shows_cache.get(key)
    if cached and time.time() - cached[0] < STARTED_SHOWS_CACHE_TTL:
        return cached[1]

    try:
        data = await _call("get_history", {
            "user_id": user_id,
            "section_id": section_id,
            "media_type": "episode",
            "length": 5000,
        })
    except Exception as e:
        log.warning(f"Tautulli started_shows_in_section failed: {e}")
        return set()

    shows: set[int] = set()
    for h in data.get("data", []):
        gpk = h.get("grandparent_rating_key")
        try:
            if gpk:
                shows.add(int(gpk))
        except (TypeError, ValueError):
            continue

    _started_shows_cache[key] = (time.time(), shows)
    return shows


async def watched_movies(user_id: int) -> set[tuple[str, int]]:
    """Return a set of (lower_title, year) tuples for every movie this user has fully watched.

    Cached for MOVIE_CACHE_TTL seconds per user — one Tautulli call yields the whole set,
    avoiding N lookups when annotating search/recent lists.
    """
    cached = _movie_cache.get(user_id)
    if cached and time.time() - cached[0] < MOVIE_CACHE_TTL:
        return cached[1]

    try:
        data = await _call("get_history", {
            "user_id": user_id,
            "media_type": "movie",
            "length": 5000,
        })
    except Exception as e:
        log.warning(f"Tautulli watched_movies failed: {e}")
        return set()

    out: set[tuple[str, int]] = set()
    for h in data.get("data", []):
        if (h.get("watched_status") or 0) < WATCHED_THRESHOLD:
            continue
        title = (h.get("title") or "").strip().lower()
        year = h.get("year") or 0
        if title:
            try:
                out.add((title, int(year)))
            except (TypeError, ValueError):
                out.add((title, 0))

    _movie_cache[user_id] = (time.time(), out)
    return out
