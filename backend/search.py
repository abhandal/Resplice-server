import asyncio
import logging
import time

from fastapi import APIRouter, Request, HTTPException, Query

from backend import sonarr, radarr, tautulli, watch_data
from backend.plex_auth import require_user, get_user_sections, get_all_users
from backend.config import PLEX_TOKEN, PLEX_SERVER_URL, HIDDEN_LIBRARIES

log = logging.getLogger("plex-support.search")
router = APIRouter(prefix="/api")

# Cache: maps Plex library section_id -> set of root folder paths
_section_paths: dict[int, set[str]] = {}
# Cache: maps Plex library section_id -> human-readable title (e.g. "Movies", "Anime")
_section_titles: dict[int, str] = {}
# Cache: section_id -> "movie" / "show"
_section_types: dict[int, str] = {}
# Cache: section_id -> total item count (refreshed alongside library cache)
_section_totals: dict[int, int] = {}
# Library titles to exclude from "recently watched" surfaces
RECENT_HIDDEN_LIBRARIES = HIDDEN_LIBRARIES
# Library titles to exclude from stats surfaces too
STATS_HIDDEN_LIBRARIES = HIDDEN_LIBRARIES

# Cache: (type, lower_title, year) -> Plex ratingKey, for Tautulli watched lookups
_plex_rating_keys: dict[tuple[str, str, int], int] = {}


async def _find_plex_rating_key(media_type: str, title: str, year: int | None) -> int | None:
    """Find a Plex ratingKey for a Sonarr/Radarr title via Plex's /search endpoint.

    media_type: 'show' or 'movie'. Cached in-memory after first lookup.
    """
    if not title:
        return None
    key = (media_type, title.lower(), year or 0)
    cached = _plex_rating_keys.get(key)
    if cached is not None:
        return cached or None  # 0 means "we already searched and didn't find it"

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(
                f"{PLEX_SERVER_URL}/search",
                headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
                params={"query": title},
            )
            resp.raise_for_status()
            md = resp.json().get("MediaContainer", {}).get("Metadata", [])
    except Exception as e:
        log.warning(f"Plex search failed for {title!r}: {e}")
        return None

    title_lower = title.lower()
    best: int | None = None
    for item in md:
        if item.get("type") != media_type:
            continue
        if (item.get("title") or "").lower() != title_lower:
            continue
        if year and item.get("year") and int(item["year"]) != int(year):
            continue
        try:
            best = int(item.get("ratingKey"))
            break
        except (TypeError, ValueError):
            continue

    _plex_rating_keys[key] = best or 0
    return best

# Library cache — refreshed every 5 minutes by background task
_sonarr_cache: list[dict] = []
_radarr_cache: list[dict] = []
_cache_updated: float = 0
CACHE_TTL = 300  # 5 minutes


async def refresh_library_cache():
    """Fetch full Sonarr + Radarr libraries into memory, plus Plex section totals.

    Mutates the existing _sonarr_cache / _radarr_cache lists in place so any module
    that did `from backend.search import _sonarr_cache` keeps seeing fresh data.
    Reassigning would orphan those bindings.
    """
    global _cache_updated
    try:
        s_lib, r_lib = await asyncio.gather(sonarr.library(), radarr.library())
        _sonarr_cache.clear()
        _sonarr_cache.extend(s_lib)
        _radarr_cache.clear()
        _radarr_cache.extend(r_lib)
        _cache_updated = time.time()
        log.info(f"Library cache refreshed: {len(s_lib)} series, {len(r_lib)} movies")
    except Exception as e:
        log.warning(f"Failed to refresh library cache: {e}")
    try:
        await _refresh_section_totals()
    except Exception as e:
        log.warning(f"Failed to refresh section totals: {e}")


async def _ensure_cache():
    if not _cache_updated or (time.time() - _cache_updated) > CACHE_TTL:
        await refresh_library_cache()


async def _refresh_section_totals():
    """Per-section item count (totalSize) — fast Container-Size=0 query per section."""
    import httpx
    if not _section_titles:
        await _build_section_paths()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            for sec_id in list(_section_titles.keys()):
                try:
                    resp = await c.get(
                        f"{PLEX_SERVER_URL}/library/sections/{sec_id}/all",
                        headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json",
                                 "X-Plex-Container-Start": "0", "X-Plex-Container-Size": "0"},
                    )
                    resp.raise_for_status()
                    total = int(resp.json().get("MediaContainer", {}).get("totalSize", 0))
                    _section_totals[sec_id] = total
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"Failed to refresh section totals: {e}")


async def _build_section_paths():
    """Map Plex library sections to their root paths."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(
                f"{PLEX_SERVER_URL}/library/sections",
                headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        _section_paths.clear()
        _section_titles.clear()
        _section_types.clear()
        for section in data.get("MediaContainer", {}).get("Directory", []):
            section_id = int(section.get("key", 0))
            title = section.get("title", "")
            sec_type = section.get("type", "")  # "movie" or "show"
            if title:
                _section_titles[section_id] = title
            if sec_type:
                _section_types[section_id] = sec_type
            paths = set()
            for loc in section.get("Location", []):
                p = loc.get("path", "")
                if p:
                    paths.add(p.rstrip("/"))
            if paths:
                _section_paths[section_id] = paths
    except Exception as e:
        log.warning(f"Failed to build section paths: {e}")


def _item_accessible(root_path: str, user_section_ids: list[int]) -> bool:
    """Check if a media item's root path is in one of the user's accessible sections."""
    root = root_path.rstrip("/")
    for sid in user_section_ids:
        section_paths = _section_paths.get(sid, set())
        for sp in section_paths:
            if root == sp or root.startswith(sp + "/") or sp.startswith(root + "/"):
                return True
    return False


def _match(title: str, query: str) -> bool:
    """Case-insensitive substring match."""
    return query.lower() in title.lower()


async def _check_series_access(request: Request, series_id: int):
    """Verify the user has access to this series. Raises 403 if not."""
    user = require_user(request)
    cached = get_all_users().get(user["uid"], {})
    if cached.get("is_admin"):
        return
    sections = await get_user_sections(user["uid"])
    if not sections:
        # Cache expired — allow access since they were already validated at login
        return
    if not _section_paths:
        await _build_section_paths()
    for s in _sonarr_cache:
        if s.get("id") == series_id:
            if not _item_accessible(s.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")
            return
    raise HTTPException(404, "Series not found")


async def _check_movie_access(request: Request, movie_id: int):
    """Verify the user has access to this movie. Raises 403 if not."""
    user = require_user(request)
    cached = get_all_users().get(user["uid"], {})
    if cached.get("is_admin"):
        return
    sections = await get_user_sections(user["uid"])
    if not sections:
        return
    if not _section_paths:
        await _build_section_paths()
    for m in _radarr_cache:
        if m.get("id") == movie_id:
            if not _item_accessible(m.get("rootFolderPath", ""), sections):
                raise HTTPException(403, "You don't have access to this content")
            return
    raise HTTPException(404, "Movie not found")


@router.get("/search")
async def search(
    request: Request,
    q: str = Query(..., min_length=1),
):
    user = require_user(request)
    is_admin = get_all_users().get(user["uid"], {}).get("is_admin", False)
    sections = await get_user_sections(user["uid"])

    if not _section_paths:
        await _build_section_paths()

    await _ensure_cache()

    # If sections cache expired, show all content (user was validated at login)

    # Prefer persisted Plex Community data (cross-server). Fall back to Tautulli.
    watched_movie_set: set[tuple[str, int]] = set()
    if watch_data.has_data(user["uid"]):
        watched_movie_set = watch_data.watched_movies(user["uid"])
    elif tautulli.is_configured():
        watched_movie_set = await tautulli.watched_movies(user["uid"])

    results = []
    query = q.strip()

    for s in _sonarr_cache:
        title = s.get("title", "")
        if not _match(title, query):
            continue
        # Hide series with no downloaded episodes (nothing to fix)
        stats = s.get("statistics", {})
        if stats.get("episodeFileCount", 0) == 0 and stats.get("sizeOnDisk", 0) == 0:
            continue
        root_path = s.get("rootFolderPath", "")
        if sections and not _item_accessible(root_path, sections):
            continue
        poster = next((img.get("remoteUrl", "") for img in s.get("images", []) if img.get("coverType") == "poster"), "")
        results.append({
            "type": "series",
            "id": s["id"],
            "title": title,
            "year": s.get("year"),
            "seasonCount": s.get("statistics", {}).get("seasonCount") or len(s.get("seasons", [])),
            "genres": s.get("genres", [])[:3],
            "poster": poster,
        })

    for m in _radarr_cache:
        title = m.get("title", "")
        if not _match(title, query):
            continue
        # Hide unreleased movies (nothing to fix or grab)
        if not m.get("hasFile", False) and m.get("status") not in ("released",):
            continue
        root_path = m.get("rootFolderPath", "")
        if sections and not _item_accessible(root_path, sections):
            continue
        movie_file = m.get("movieFile") or {}
        poster = next((img.get("remoteUrl", "") for img in m.get("images", []) if img.get("coverType") == "poster"), "")
        watched = (title.lower(), m.get("year") or 0) in watched_movie_set
        results.append({
            "type": "movie",
            "id": m["id"],
            "tmdbId": m.get("tmdbId"),
            "title": title,
            "year": m.get("year"),
            "hasFile": m.get("hasFile", False),
            "watched": watched,
            "fileId": movie_file.get("id"),
            "fileSize": movie_file.get("size", 0),
            "quality": movie_file.get("quality", {}).get("quality", {}).get("name", ""),
            "genres": m.get("genres", [])[:3],
            "poster": poster,
        })

    # Sort: shows first, then movies, limit to 20
    results.sort(key=lambda r: (0 if r["type"] == "series" else 1, r.get("title", "")))
    return results[:20]


@router.get("/recently-watched")
async def recently_watched(request: Request):
    """Get the user's recently watched items from Plex, matched to Sonarr/Radarr library."""
    user = require_user(request)
    await _ensure_cache()
    if not _section_titles:
        await _build_section_paths()

    # Map plex-support uid to Plex local accountID (admin is 1, others match)
    is_admin = get_all_users().get(user["uid"], {}).get("is_admin", False)
    account_id = 1 if is_admin else user["uid"]

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(
                f"{PLEX_SERVER_URL}/status/sessions/history/all",
                headers={"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"},
                params={
                    "sort": "viewedAt:desc",
                    "accountID": account_id,
                    "X-Plex-Container-Size": 50,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning(f"Failed to fetch Plex history: {e}")
        return []

    metadata = data.get("MediaContainer", {}).get("Metadata", [])

    # Per-user watched-movies set for the badge (Plex Community first, Tautulli fallback)
    watched_movie_set: set[tuple[str, int]] = set()
    if watch_data.has_data(user["uid"]):
        watched_movie_set = watch_data.watched_movies(user["uid"])
    elif tautulli.is_configured():
        watched_movie_set = await tautulli.watched_movies(user["uid"])

    # Build lookup maps from cache
    sonarr_by_title = {}
    for s in _sonarr_cache:
        t = s.get("title", "").lower()
        if t:
            sonarr_by_title[t] = s

    radarr_by_title = {}
    for m in _radarr_cache:
        t = m.get("title", "").lower()
        if t:
            radarr_by_title[t] = m

    results = []
    seen: set[tuple[str, int]] = set()  # dedupe by (type, sonarr/radarr id)

    for item in metadata:
        item_type = item.get("type")
        # Plex history returns librarySectionID but not the title — resolve via cache
        sec_id_raw = item.get("librarySectionID")
        try:
            sec_id = int(sec_id_raw) if sec_id_raw is not None else 0
        except (TypeError, ValueError):
            sec_id = 0
        library = _section_titles.get(sec_id, "")
        if library in RECENT_HIDDEN_LIBRARIES:
            continue

        if item_type == "episode":
            show_title = (item.get("grandparentTitle") or "").lower()
            s = sonarr_by_title.get(show_title)
            if not s:
                continue
            key = ("series", s["id"])
            if key in seen:
                continue
            seen.add(key)
            poster = next((img.get("remoteUrl", "") for img in s.get("images", []) if img.get("coverType") == "poster"), "")
            results.append({
                "type": "series",
                "id": s["id"],
                "title": s.get("title", ""),
                "year": s.get("year"),
                "seasonCount": s.get("statistics", {}).get("seasonCount") or len(s.get("seasons", [])),
                "genres": s.get("genres", [])[:3],
                "poster": poster,
                "library": library,
            })

        elif item_type == "movie":
            movie_title = (item.get("title") or "").lower()
            m = radarr_by_title.get(movie_title)
            if not m:
                continue
            key = ("movie", m["id"])
            if key in seen:
                continue
            seen.add(key)
            movie_file = m.get("movieFile") or {}
            poster = next((img.get("remoteUrl", "") for img in m.get("images", []) if img.get("coverType") == "poster"), "")
            watched = ((m.get("title", "") or "").lower(), m.get("year") or 0) in watched_movie_set
            results.append({
                "type": "movie",
                "id": m["id"],
                "tmdbId": m.get("tmdbId"),
                "title": m.get("title", ""),
                "year": m.get("year"),
                "hasFile": m.get("hasFile", False),
                "watched": watched,
                "fileId": movie_file.get("id"),
                "fileSize": movie_file.get("size", 0),
                "quality": movie_file.get("quality", {}).get("quality", {}).get("name", ""),
                "genres": m.get("genres", [])[:3],
                "poster": poster,
                "library": library,
            })

        if len(results) >= 30:
            break

    return results


@router.get("/series/{series_id}/seasons")
async def get_seasons(request: Request, series_id: int):
    user = require_user(request)
    await _check_series_access(request, series_id)
    # Get series title, poster, TMDB ID and descriptive fields from cache
    series_title = "Unknown"
    series_poster = ""
    series_tmdb_id = None
    series_meta: dict = {}
    for s in _sonarr_cache:
        if s.get("id") == series_id:
            series_title = s.get("title", "Unknown")
            series_poster = next((img.get("remoteUrl", "") for img in s.get("images", []) if img.get("coverType") == "poster"), "")
            series_tmdb_id = s.get("tmdbId")
            rating_value = (s.get("ratings") or {}).get("value")
            series_meta = {
                "year": s.get("year"),
                "overview": s.get("overview", ""),
                "network": s.get("network", ""),
                "certification": s.get("certification", ""),
                "genres": s.get("genres", [])[:4],
                "runtime": s.get("runtime", 0),
                "seriesStatus": s.get("status", ""),
                # Sonarr carries one rating rather than a set, unlike Radarr.
                "rating": rating_value if isinstance(rating_value, (int, float)) else None,
            }
            break

    # Per-season watched counts come from already-persisted Plex history (no extra calls)
    watched_per_season: dict[int, int] = {}
    if series_title and watch_data.has_data(user["uid"]):
        watched_per_season = watch_data.watched_count_per_season(user["uid"], series_title)

    eps = await sonarr.episodes(series_id)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    seasons: dict[int, dict] = {}
    for ep in eps:
        s = ep.get("seasonNumber", 0)
        if s not in seasons:
            seasons[s] = {
                "season": s, "episodeCount": 0, "hasFiles": 0,
                "airedCount": 0, "firstAirDate": None,
                "watchedCount": watched_per_season.get(s, 0),
            }
        seasons[s]["episodeCount"] += 1
        if ep.get("hasFile"):
            seasons[s]["hasFiles"] += 1
        # Track aired episodes and earliest future air date
        air_str = ep.get("airDateUtc")
        if air_str:
            try:
                air = datetime.fromisoformat(air_str.replace("Z", "+00:00"))
                if air <= now:
                    seasons[s]["airedCount"] += 1
                elif seasons[s]["firstAirDate"] is None or air_str < seasons[s]["firstAirDate"]:
                    seasons[s]["firstAirDate"] = air_str
            except Exception:
                seasons[s]["airedCount"] += 1

    # Add status tag for seasons with no aired episodes or entirely missing
    for sdata in seasons.values():
        if sdata["airedCount"] == 0 and sdata["hasFiles"] == 0:
            # Not aired yet
            if sdata["firstAirDate"]:
                try:
                    air = datetime.fromisoformat(sdata["firstAirDate"].replace("Z", "+00:00"))
                    sdata["status"] = air.strftime("%b %d, %Y")
                except Exception:
                    sdata["status"] = "TBA"
            else:
                sdata["status"] = "TBA"
        elif sdata["airedCount"] > 0 and sdata["hasFiles"] == 0:
            # Aired but entirely missing — hide from episode view, show request link
            sdata["status"] = "missing"
        else:
            sdata["status"] = None
        del sdata["airedCount"]
        del sdata["firstAirDate"]

    return {
        "title": series_title,
        "poster": series_poster,
        "tmdbId": series_tmdb_id,
        **series_meta,
        "seasons": sorted(seasons.values(), key=lambda x: x["season"]),
    }


@router.get("/series/{series_id}/episodes")
async def get_episodes(request: Request, series_id: int, season: int = Query(...)):
    user = require_user(request)
    await _check_series_access(request, series_id)
    eps = await sonarr.episodes(series_id, season)

    # Build per-user watched set for this season.
    # Prefer persisted Plex Community history (matched by show title); fall back to Tautulli.
    watched_set: set[tuple[int, int]] = set()
    series_title = ""
    series_year = None
    for s in _sonarr_cache:
        if s.get("id") == series_id:
            series_title = s.get("title", "")
            series_year = s.get("year")
            break

    if series_title and watch_data.has_data(user["uid"]):
        watched_set = watch_data.watched_episodes_for_show(user["uid"], series_title)
    elif tautulli.is_configured() and series_title:
        rk = await _find_plex_rating_key("show", series_title, series_year)
        if rk:
            watched_set = await tautulli.watched_episodes(user["uid"], rk)

    result = []
    for ep in sorted(eps, key=lambda e: e.get("episodeNumber", 0)):
        # Skip unaired episodes — nothing to fix or grab
        if not ep.get("hasFile") and not ep.get("airDateUtc"):
            continue
        if not ep.get("hasFile") and ep.get("airDateUtc"):
            from datetime import datetime, timezone
            try:
                air = datetime.fromisoformat(ep["airDateUtc"].replace("Z", "+00:00"))
                if air > datetime.now(timezone.utc):
                    continue
            except Exception:
                pass
        ep_num = ep.get("episodeNumber", 0)
        entry = {
            "id": ep["id"],
            "episodeNumber": ep_num,
            "title": ep.get("title", ""),
            "hasFile": ep.get("hasFile", False),
            "episodeFileId": ep.get("episodeFileId", 0),
            "watched": (season, ep_num) in watched_set,
        }
        if ep.get("hasFile") and ep.get("episodeFileId"):
            try:
                f = await sonarr.episode_file(ep["episodeFileId"])
                entry["fileName"] = f.get("path", "").rsplit("/", 1)[-1]
                entry["fileSize"] = f.get("size", 0)
                entry["quality"] = f.get("quality", {}).get("quality", {}).get("name", "")
            except Exception:
                pass
        result.append(entry)
    return result


@router.get("/movie/{movie_id}")
async def get_movie(request: Request, movie_id: int):
    require_user(request)
    await _check_movie_access(request, movie_id)
    m = await radarr.movie(movie_id)
    movie_file = m.get("movieFile") or {}

    poster = next((img.get("remoteUrl", "") for img in m.get("images", []) if img.get("coverType") == "poster"), "")
    ratings = m.get("ratings") or {}

    def rating(source: str):
        """Radarr nests each source as {votes, value}; absent sources are None."""
        value = (ratings.get(source) or {}).get("value")
        return value if isinstance(value, (int, float)) else None

    return {
        "id": m["id"],
        "title": m.get("title", "Unknown"),
        "year": m.get("year"),
        "hasFile": m.get("hasFile", False),
        "fileId": movie_file.get("id"),
        "fileName": movie_file.get("path", "").rsplit("/", 1)[-1] if movie_file.get("path") else "",
        "fileSize": movie_file.get("size", 0),
        "quality": movie_file.get("quality", {}).get("quality", {}).get("name", ""),
        # Descriptive fields, for clients that show more than the file. Radarr
        # already has all of this; passing it through costs nothing because the
        # movie was fetched anyway.
        "tmdbId": m.get("tmdbId"),
        "poster": poster,
        "overview": m.get("overview", ""),
        "runtime": m.get("runtime", 0),
        "certification": m.get("certification", ""),
        "studio": m.get("studio", ""),
        "genres": m.get("genres", [])[:4],
        "ratings": {
            "tmdb": rating("tmdb"),
            "imdb": rating("imdb"),
            "rottenTomatoes": rating("rottenTomatoes"),
        },
    }
