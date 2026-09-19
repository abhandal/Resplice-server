"""Per-user watch stats — surfaced from Tautulli."""

import asyncio
import logging
import time

from fastapi import APIRouter, HTTPException, Query, Request

from backend import tautulli, watch_data
from backend.plex_auth import require_user, get_user_sections, get_all_users
from backend.search import (
    _section_titles, _section_types, _section_totals, _sonarr_cache, _radarr_cache,
    _build_section_paths, _refresh_section_totals, STATS_HIDDEN_LIBRARIES,
)

log = logging.getLogger("plex-support.stats")
router = APIRouter(prefix="/api/stats")


# --- Light-hearted copy ----------------------------------------------------

# Tone tier picked from hours watched in the chosen period. Order: ascending.
_TIERS: list[tuple[float, str, str]] = [
    (1,    "Just Curious",        "Mostly here for the popcorn."),
    (5,    "Touch-Grass Certified", "Healthy balance — your plants are thriving."),
    (15,   "Casual Connoisseur",   "A respectable evening-on-the-couch operator."),
    (40,   "Couch Warmer",         "Your couch knows your shape now."),
    (80,   "Plex-Pilled",          "We see you, weeknight binger."),
    (150,  "Marathon Enthusiast",  "Eject button optional. Snacks mandatory."),
    (300,  "Streaming Sommelier",  "Aged like fine WEB-DL."),
    (10**9, "Legend Status",        "We are contractually obligated to mention sunlight exists."),
]


def _format_duration(seconds: int) -> dict:
    """Produce both a compact label and a 'fun' description."""
    hours_total = seconds / 3600
    days_total = hours_total / 24

    if hours_total < 1:
        compact = f"{int(seconds // 60)}m"
    elif hours_total < 100:
        compact = f"{hours_total:.1f}h"
    else:
        compact = f"{int(hours_total):,}h"

    # Fun comparison units
    avg_movie = 6300  # ~1h45m
    movies = seconds // avg_movie
    sleep_cycles = hours_total / 8

    if hours_total < 2:
        fun = "Barely a feature film"
    elif hours_total < 24:
        fun = f"≈ {movies:,} movies of popcorn time"
    elif days_total < 3:
        fun = f"≈ {int(days_total * 24):,} hours straight"
    elif days_total < 14:
        fun = f"{days_total:.1f} full days, no breaks"
    elif days_total < 60:
        fun = f"{int(sleep_cycles):,} skipped sleep cycles"
    else:
        weeks = days_total / 7
        fun = f"{weeks:.1f} solid weeks of screen time"

    return {"compact": compact, "fun": fun, "hours": round(hours_total, 1), "days": round(days_total, 2)}


def _tier_for(seconds: int) -> dict:
    hours = seconds / 3600
    for upper, label, blurb in _TIERS:
        if hours < upper:
            return {"label": label, "blurb": blurb}
    return {"label": _TIERS[-1][1], "blurb": _TIERS[-1][2]}


_LIBRARY_TIERS: list[tuple[float, str]] = [
    (0.001, "First day on the job? Bold strategy."),
    (0.01,  "A toe in the water. We don't bite."),
    (0.05,  "Sampler-platter mode."),
    (0.15,  "Browsing like you mean it."),
    (0.30,  "Now you're cooking."),
    (0.50,  "Power-user energy."),
    (0.75,  "We're slightly intimidated."),
    (1.0,   "Library terrorist. Please add new content."),
    (10**9, "Mathematically impossible. We're calling Guinness."),
]


def _library_blurb(pct: float) -> str:
    if pct <= 0:
        return "Untouched. The buffet awaits."
    for upper, blurb in _LIBRARY_TIERS:
        if pct < upper:
            return blurb
    return _LIBRARY_TIERS[-1][1]


def _series_in_section(series: dict, sec_id: int) -> bool:
    """Check if a Sonarr series' rootFolderPath belongs to a Plex section."""
    from backend.search import _section_paths
    root = (series.get("rootFolderPath") or "").rstrip("/")
    if not root:
        return False
    paths = _section_paths.get(sec_id, set())
    for sp in paths:
        if root == sp or root.startswith(sp + "/") or sp.startswith(root + "/"):
            return True
    return False


def _noun_for(sec_type: str, title: str) -> str:
    """Pick a friendly singular noun for the library."""
    if sec_type == "movie":
        return "movie"
    if title.lower() == "anime":
        return "anime"
    return "show"


async def _library_stats(user_id: int) -> list[dict]:
    """Per-library counts and watched-percentage for the given user.

    Filters by the user's accessible sections (admin sees all). Excludes Fitness etc.
    """
    if not _section_titles:
        await _build_section_paths()
    if not _section_totals:
        await _refresh_section_totals()

    # Determine which sections this user can see
    allowed = set(await get_user_sections(user_id))
    is_admin = get_all_users().get(user_id, {}).get("is_admin", False)

    out: list[dict] = []
    for sec_id, title in _section_titles.items():
        if title in STATS_HIDDEN_LIBRARIES:
            continue
        # Honor user access — admin or empty allowed-set means show all
        if not is_admin and allowed and sec_id not in allowed:
            continue

        total = int(_section_totals.get(sec_id, 0))
        if total <= 0:
            continue

        sec_type = _section_types.get(sec_id, "")
        if sec_type == "movie":
            # All movies live in this section; watched_movies is the global movie set
            if watch_data.has_data(user_id):
                watched_count = len(watch_data.watched_movies(user_id))
            elif tautulli.is_configured():
                watched_count = len(await tautulli.watched_movies(user_id))
            else:
                watched_count = 0
            verb = "watched"
        else:
            # Show / anime — count distinct shows the user has started in this section.
            # Plex Community history doesn't include section_id, so we cross-reference
            # the user's started_shows titles against Sonarr's per-section root paths.
            if watch_data.has_data(user_id):
                started_titles = watch_data.started_shows(user_id)
                # Filter to titles that match a Sonarr series whose root path lives in this section
                section_titles_lower = {
                    s.get("title", "").lower()
                    for s in _sonarr_cache
                    if _series_in_section(s, sec_id)
                }
                watched_count = sum(1 for t in started_titles if t.lower() in section_titles_lower)
            elif tautulli.is_configured():
                watched_count = len(await tautulli.started_shows_in_section(user_id, sec_id))
            else:
                watched_count = 0
            verb = "started"

        # A user can sometimes have more "watched" than current library total (deletes, renames)
        capped = min(watched_count, total)
        pct = capped / total if total else 0
        noun = _noun_for(sec_type, title)
        out.append({
            "sectionId": sec_id,
            "library": title,
            "type": sec_type,
            "noun": noun,
            "total": total,
            "watched": capped,
            "verb": verb,
            "pct": round(pct * 100, 1),
            "blurb": _library_blurb(pct),
        })

    # Stable order: Movies, TV Shows, Anime, others
    order = {"Movies": 0, "TV Shows": 1, "Anime": 2}
    out.sort(key=lambda x: (order.get(x["library"], 99), x["library"]))
    return out


def _filter_breakdown(rows: list[dict]) -> list[dict]:
    """Drop hidden libraries and roll up to compact per-type entries for display."""
    out = []
    for r in rows:
        if r.get("library") in STATS_HIDDEN_LIBRARIES:
            continue
        out.append({
            "library": r.get("library", ""),
            "type": r.get("type", ""),
            "seconds": int(r.get("seconds") or 0),
            "plays": int(r.get("plays") or 0),
        })
    # Sort: Movies, TV Shows, Anime, then others by hours desc
    order = {"Movies": 0, "TV Shows": 1, "Anime": 2}
    out.sort(key=lambda x: (order.get(x["library"], 99), -x["seconds"]))
    return out


def _annotate_period(period: dict, breakdown: list[dict] | None = None) -> dict:
    seconds = period.get("seconds", 0)
    plays = period.get("plays", 0)
    return {
        **period,
        "duration": _format_duration(seconds),
        "tier": _tier_for(seconds),
        "playsLabel": f"{plays:,} play{'s' if plays != 1 else ''}",
        "byType": _filter_breakdown(breakdown or []),
    }


def _show_section(show_title: str) -> tuple[int, str] | tuple[None, None]:
    """Locate which Plex section a show title belongs to via Sonarr → root path mapping.
    Returns (section_id, library_title) or (None, None) if not in our library."""
    title_lower = show_title.lower()
    for s in _sonarr_cache:
        if (s.get("title") or "").lower() != title_lower:
            continue
        root = (s.get("rootFolderPath") or "").rstrip("/")
        if not root:
            return (None, None)
        from backend.search import _section_paths
        for sec_id, paths in _section_paths.items():
            for sp in paths:
                if root == sp or root.startswith(sp + "/") or sp.startswith(root + "/"):
                    return (sec_id, _section_titles.get(sec_id, ""))
        return (None, None)
    return (None, None)


def _cross_server_breakdown(user_id: int, since: float = 0) -> tuple[int, int, list[dict]]:
    """Compute cross-server (seconds, plays, per-library breakdown) for the given
    window using the persisted Plex Community history. Movies → Movies library;
    episodes classified by which Plex section their show lives in.
    since=0 means all-time."""
    totals = watch_data.cross_server_totals(user_id, since=since)

    # Aggregate episode seconds per library by mapping each show to its Plex section
    library_secs: dict[str, dict] = {}  # library_title -> {seconds, plays, type}
    for show, secs in totals["byShow"].items():
        sec_id, lib_title = _show_section(show)
        if not lib_title:
            lib_title = "Other"
            sec_type = ""
        else:
            sec_type = _section_types.get(sec_id, "show")
        bucket = library_secs.setdefault(lib_title, {"seconds": 0, "plays": 0, "type": sec_type})
        bucket["seconds"] += secs

    # Episode plays per library — we lose per-show plays granularity but rough sum is fine:
    # distribute episodePlays proportionally to each library's seconds share.
    total_ep_secs = totals["episodeSeconds"] or 1
    for lib_title, bucket in library_secs.items():
        bucket["plays"] = int(round(totals["episodePlays"] * bucket["seconds"] / total_ep_secs))

    # Add Movies library
    if totals["movieSeconds"] > 0:
        library_secs.setdefault("Movies", {"seconds": 0, "plays": 0, "type": "movie"})
        library_secs["Movies"]["seconds"] += totals["movieSeconds"]
        library_secs["Movies"]["plays"] += totals["moviePlays"]

    rows = [
        {"library": lib, "type": v["type"], "seconds": v["seconds"], "plays": v["plays"]}
        for lib, v in library_secs.items()
        if lib not in STATS_HIDDEN_LIBRARIES
    ]
    return totals["seconds"], totals["plays"], rows


async def _summary_with_breakdowns(user_id: int) -> dict:
    """Per-period totals + per-library breakdowns. When persisted Plex Community
    history is available, ALL periods come from it (cross-server, true to Plex's
    own numbers). Otherwise we fall back to Tautulli (this server only)."""
    from datetime import datetime
    today = datetime.now()
    ytd_days = (today - datetime(today.year, 1, 1)).days + 1
    now = time.time()

    if watch_data.has_data(user_id):
        # Plex Community has plays back to account creation — use it for every period
        windows = {
            "30days": now - 30 * 86400,
            "90days": now - 90 * 86400,
            "ytd": datetime(today.year, 1, 1).timestamp(),
            "allTime": 0,
        }
        raw: dict[str, dict] = {}
        breakdowns: dict[str, list] = {}
        for k, since in windows.items():
            secs, plays, rows = _cross_server_breakdown(user_id, since=since)
            raw[k] = {"seconds": secs, "plays": plays}
            breakdowns[k] = rows
        return {k: _annotate_period(v, breakdowns.get(k, [])) for k, v in raw.items()}

    # Fallback path — Tautulli (this-server-only)
    raw, b30, b90, byt, ball = await asyncio.gather(
        tautulli.user_summary(user_id),
        tautulli.user_library_breakdown(user_id, 30),
        tautulli.user_library_breakdown(user_id, 90),
        tautulli.user_library_breakdown(user_id, ytd_days),
        tautulli.user_library_breakdown(user_id, 0),
    )
    breakdowns = {"30days": b30, "90days": b90, "ytd": byt, "allTime": ball}
    return {k: _annotate_period(v, breakdowns.get(k, [])) for k, v in raw.items()}


# --- Routes ----------------------------------------------------------------

@router.get("/summary")
async def summary(request: Request):
    """Top-of-page card data: per-period totals + light-hearted copy + per-type breakdown."""
    user = require_user(request)
    if not tautulli.is_configured():
        raise HTTPException(503, "Tautulli is not configured")

    periods = await _summary_with_breakdowns(user["uid"])
    return {
        "periods": periods,
        "username": user.get("name", ""),
    }


_DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _day_of_week_with_libraries(user_id: int, since: float = 0) -> list[dict]:
    """Per day-of-week + per-library breakdown — plays count split into Movies / TV Shows / Anime / Other."""
    from datetime import date
    plays = watch_data.all_plays(user_id, since=since)

    # Cache show → library lookup once per show, since _show_section walks Sonarr cache
    show_lib_cache: dict[str, str] = {}

    def show_library(show: str) -> str:
        if show in show_lib_cache:
            return show_lib_cache[show]
        _, lib = _show_section(show)
        result = lib or "Other"
        show_lib_cache[show] = result
        return result

    by_day_lib: dict[int, dict[str, int]] = {i: {} for i in range(7)}
    for p in plays:
        if not p.get("d"):
            continue
        dow = date.fromtimestamp(p["d"]).weekday()
        if p.get("t") == "M":
            lib = "Movies"
        elif p.get("t") == "E":
            lib = show_library(p.get("s") or "")
        else:
            continue
        if lib in STATS_HIDDEN_LIBRARIES:
            continue
        by_day_lib[dow][lib] = by_day_lib[dow].get(lib, 0) + 1

    order = {"Movies": 0, "TV Shows": 1, "Anime": 2}
    out = []
    for dow in range(7):
        libs = by_day_lib.get(dow, {})
        total = sum(libs.values())
        breakdown = sorted(
            [{"library": k, "plays": v} for k, v in libs.items()],
            key=lambda x: (order.get(x["library"], 99), -x["plays"]),
        )
        out.append({"day": _DOW_NAMES[dow], "plays": total, "byLibrary": breakdown})
    return out


def _fun_stats(user_id: int, since: float = 0) -> dict:
    """Cross-reference raw plays with Sonarr/Radarr metadata to derive fun aggregates,
    scoped to a window (since=0 means all-time). No extra API calls."""
    if not watch_data.has_data(user_id):
        return {}

    plays = watch_data.all_plays(user_id, since=since)
    if not plays:
        return {}

    # Build title->record lookups once
    sonarr_by_title = {(s.get("title") or "").lower(): s for s in _sonarr_cache}
    radarr_by_title = {((m.get("title") or "").lower(), int(m.get("year") or 0)): m for m in _radarr_cache}

    genre_secs: dict[str, int] = {}
    network_secs: dict[str, int] = {}
    decade_secs: dict[int, int] = {}
    movie_runtimes: list[int] = []  # in minutes
    languages: dict[str, int] = {}
    year_secs: dict[int, int] = {}  # for "your year"

    for p in plays:
        dur = int(p.get("du") or 0)
        if p.get("t") == "M":
            year = int(p.get("y") or 0)
            key = (p.get("ti", "").lower(), year)
            m = radarr_by_title.get(key)
            if m:
                for g in (m.get("genres") or []):
                    genre_secs[g] = genre_secs.get(g, 0) + dur
                if year:
                    decade = (year // 10) * 10
                    decade_secs[decade] = decade_secs.get(decade, 0) + dur
                    year_secs[year] = year_secs.get(year, 0) + dur
                rt = int(m.get("runtime") or 0)
                if rt:
                    movie_runtimes.append(rt)
                lang = (m.get("originalLanguage") or {}).get("name", "")
                if lang:
                    languages[lang] = languages.get(lang, 0) + dur
        elif p.get("t") == "E":
            show = (p.get("s") or "").lower()
            s = sonarr_by_title.get(show)
            if s:
                for g in (s.get("genres") or []):
                    genre_secs[g] = genre_secs.get(g, 0) + dur
                year = int(s.get("year") or 0)
                if year:
                    decade = (year // 10) * 10
                    decade_secs[decade] = decade_secs.get(decade, 0) + dur
                    year_secs[year] = year_secs.get(year, 0) + dur
                net = s.get("network", "")
                if net:
                    network_secs[net] = network_secs.get(net, 0) + dur
                lang = (s.get("originalLanguage") or {}).get("name", "")
                if lang:
                    languages[lang] = languages.get(lang, 0) + dur

    top_genres = sorted(
        [{"name": g, "seconds": s} for g, s in genre_secs.items()],
        key=lambda x: -x["seconds"],
    )[:6]
    top_networks = sorted(
        [{"name": n, "seconds": s} for n, s in network_secs.items()],
        key=lambda x: -x["seconds"],
    )[:5]
    decade_rows = sorted(
        [{"decade": d, "seconds": s} for d, s in decade_secs.items()],
        key=lambda x: -x["seconds"],
    )
    top_languages = sorted(
        [{"name": l, "seconds": s} for l, s in languages.items()],
        key=lambda x: -x["seconds"],
    )[:5]

    avg_movie_runtime_min = round(sum(movie_runtimes) / len(movie_runtimes)) if movie_runtimes else 0

    your_year = None
    if year_secs:
        best_year = max(year_secs, key=lambda y: year_secs[y])
        your_year = {"year": best_year, "seconds": year_secs[best_year]}

    return {
        "topGenres": top_genres,
        "topNetworks": top_networks,
        "topLanguages": top_languages,
        "decades": decade_rows,
        "avgMovieRuntimeMin": avg_movie_runtime_min,
        "yourYear": your_year,
        "comfortShow": watch_data.comfort_show(user_id, since=since),
        "powerDay": watch_data.power_day(user_id, since=since),
        "streaks": watch_data.streaks(user_id, since=since),
        "rewatch": watch_data.rewatch_ratio(user_id, since=since),
        "byDayOfWeek": _day_of_week_with_libraries(user_id, since=since),
    }




def _poster_of(item: dict) -> str:
    """First poster image on a Sonarr/Radarr record, or empty."""
    return next(
        (img.get("remoteUrl", "") for img in item.get("images", []) if img.get("coverType") == "poster"),
        "",
    )


def _attach_posters(top_shows: list[dict], top_movies: list[dict]) -> None:
    """Add artwork to the top lists, in place.

    The watch history comes from Plex and carries titles only, so the artwork
    has to be looked up in the libraries we already hold in memory. Matching is
    by lowercased title — the same basis the rest of this module uses to line
    Plex history up with Sonarr/Radarr — and anything unmatched simply gets no
    poster rather than a broken one.
    """
    from backend.search import _sonarr_cache, _radarr_cache

    shows = {(s.get("title") or "").lower(): s for s in _sonarr_cache}
    movies: dict[tuple, dict] = {}
    for m in _radarr_cache:
        title = (m.get("title") or "").lower()
        movies[(title, m.get("year") or 0)] = m
        movies.setdefault((title, 0), m)  # fall back when the year disagrees

    for show in top_shows:
        match = shows.get((show.get("title") or "").lower())
        if match:
            show["poster"] = _poster_of(match)
            show["seriesId"] = match.get("id")

    for movie in top_movies:
        title = (movie.get("title") or "").lower()
        match = movies.get((title, movie.get("year") or 0)) or movies.get((title, 0))
        if match:
            movie["poster"] = _poster_of(match)
            movie["movieId"] = match.get("id")


@router.get("/detailed")
async def detailed(
    request: Request,
    period: str = Query("30days"),
):
    """Full breakdown for the stats page — top shows/movies/platforms for the chosen period."""
    user = require_user(request)
    if not tautulli.is_configured():
        raise HTTPException(503, "Tautulli is not configured")

    from datetime import datetime
    today = datetime.now()
    days_for_period = {
        "30days": 30,
        "90days": 90,
        "ytd": (today - datetime(today.year, 1, 1)).days + 1,
        "allTime": 0,
    }
    days = days_for_period.get(period)
    if days is None:
        raise HTTPException(400, "period must be one of: 30days, 90days, ytd, allTime")

    summary_periods = await _summary_with_breakdowns(user["uid"])
    libraries = await _library_stats(user["uid"])

    # Compute the `since` epoch for the requested period so we can window plays
    now = time.time()
    period_since = {
        "30days": now - 30 * 86400,
        "90days": now - 90 * 86400,
        "ytd": datetime(today.year, 1, 1).timestamp(),
        "allTime": 0,
    }.get(period, 0)

    if watch_data.has_data(user["uid"]):
        # Cross-server, date-windowed top lists (consistent with hours)
        top_shows = watch_data.top_shows_by_episodes(user["uid"], limit=10, since=period_since)
        top_movies = watch_data.top_movies_by_plays(user["uid"], limit=10, since=period_since)
        top_shows_source = "plex"
        top_movies_source = "plex"
        # Tautulli still owns top platforms (Plex Community doesn't expose them)
        breakdown = await tautulli.user_breakdown(user["uid"], time_range_days=days, count=10)
    else:
        breakdown = await tautulli.user_breakdown(user["uid"], time_range_days=days, count=10)
        top_shows = breakdown.get("topShows", [])
        top_movies = breakdown.get("topMovies", [])
        top_shows_source = "tautulli"
        top_movies_source = "tautulli"

    _attach_posters(top_shows, top_movies)

    return {
        "period": period,
        "days": days,
        "periods": summary_periods,
        "topShows": top_shows,
        "topShowsSource": top_shows_source,
        "topMovies": top_movies,
        "topMoviesSource": top_movies_source,
        "topPlatforms": breakdown.get("topPlatforms", []),
        "libraries": libraries,
        "fun": _fun_stats(user["uid"], since=period_since),
    }
