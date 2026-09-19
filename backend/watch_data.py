"""Persistent per-user watch data — raw play log synced from Plex Community.

One JSON file per user under data/watch_history/. Stores every individual play (not
deduped) so we can date-window cross-server stats for any period (30d/90d/YTD/all).

Storage shape (per user):
    {
        "user_id": int,
        "uuid": str,
        "last_synced_at": float (epoch seconds),
        "plays": [
            {"d": <epoch>, "t": "M"|"E", "ti": "Title", "y": <year>, "du": <seconds>,
             "s": "<show>", "se": <season>, "ep": <episode>}
        ]
    }

Field key:
    d  = date (epoch seconds)
    t  = type ("M" movie, "E" episode)
    ti = title (movie title or episode title)
    y  = year (movie only)
    du = duration in seconds (item runtime; play-level duration not exposed by Plex Community)
    s  = show title (episode only)
    se = season number (episode only)
    ep = episode number (episode only)

Backward compat: legacy file shapes (deduped movies/episodes from earlier versions)
are detected at load time and discarded; the next sync starts fresh from Plex.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from backend import plex_community

log = logging.getLogger("plex-support.watch_data")

DATA_DIR = Path(__file__).parent.parent / "data" / "watch_history"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_cache: dict[int, dict] = {}
_locks: dict[int, asyncio.Lock] = {}

REFRESH_INTERVAL = 1800  # 30 min


def _path(user_id: int) -> Path:
    return DATA_DIR / f"{user_id}.json"


def _new_blank(user_id: int, uuid: str = "") -> dict:
    return {
        "user_id": int(user_id),
        "uuid": uuid,
        "last_synced_at": 0,
        "plays": [],
    }


def load(user_id: int) -> dict:
    if user_id in _cache:
        return _cache[user_id]
    p = _path(user_id)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            # Detect & discard pre-raw-plays shape (had "movies"/"episodes" keys)
            if "movies" in data or "episodes" in data:
                log.info(f"watch_data: legacy shape for user {user_id} — discarding, will re-sync")
                data = _new_blank(user_id, data.get("uuid", ""))
            elif "plays" not in data:
                data["plays"] = []
            _cache[user_id] = data
            return data
        except Exception as e:
            log.warning(f"watch_data load failed for {user_id}: {e}")
    blank = _new_blank(user_id)
    _cache[user_id] = blank
    return blank


def save(user_id: int, data: dict) -> None:
    _cache[user_id] = data
    try:
        _path(user_id).write_text(json.dumps(data, separators=(",", ":")))
    except Exception as e:
        log.warning(f"watch_data save failed for {user_id}: {e}")


def _to_play(e: dict) -> dict | None:
    mtype = e.get("type")
    d = float(e.get("date") or 0)
    dur = int(e.get("duration") or 0)
    if mtype == "MOVIE":
        title = (e.get("title") or "").strip()
        if not title:
            return None
        return {"d": d, "t": "M", "ti": title, "y": int(e.get("year") or 0), "du": dur}
    if mtype == "EPISODE":
        show = (e.get("show") or "").strip()
        season = e.get("season")
        episode = e.get("episode")
        if not show or season is None or episode is None:
            return None
        try:
            return {
                "d": d, "t": "E", "ti": (e.get("title") or "").strip(),
                "s": show, "se": int(season), "ep": int(episode), "du": dur,
            }
        except (TypeError, ValueError):
            return None
    return None


def _merge_entries(data: dict, entries: list[dict], uuid: str) -> int:
    """Append new plays to the persisted log (de-dup'd by date+key to handle re-fetches)."""
    if uuid:
        data["uuid"] = uuid

    plays = data.setdefault("plays", [])
    # Build a fingerprint set so a re-sync that overlaps doesn't duplicate
    seen: set[tuple] = set()
    for p in plays:
        seen.add(_fingerprint(p))

    added = 0
    latest_date = float(data.get("last_synced_at") or 0)
    for e in entries:
        p = _to_play(e)
        if not p:
            continue
        fp = _fingerprint(p)
        if fp in seen:
            # Backfill duration if we have it now and the existing record didn't
            for existing in plays:
                if _fingerprint(existing) == fp and not existing.get("du") and p.get("du"):
                    existing["du"] = p["du"]
                    break
            continue
        seen.add(fp)
        plays.append(p)
        added += 1
        latest_date = max(latest_date, p["d"])

    plays.sort(key=lambda x: x["d"])
    data["plays"] = plays
    data["last_synced_at"] = latest_date
    return added


def _fingerprint(p: dict) -> tuple:
    """Unique key for a play — date + media identity. Plex Community is consistent
    enough on dates that this catches re-fetched entries on incremental syncs."""
    if p.get("t") == "M":
        return ("M", round(p.get("d", 0)), p.get("ti", "").lower(), int(p.get("y") or 0))
    return ("E", round(p.get("d", 0)), p.get("s", "").lower(), int(p.get("se") or 0), int(p.get("ep") or 0))


async def sync_user(user_id: int, plex_token: str, uuid: str, *, force: bool = False) -> int:
    if not plex_token or not uuid:
        return 0
    lock = _locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        if force:
            data = _new_blank(user_id, uuid)
            _cache[user_id] = data
        else:
            data = load(user_id)
        since = 0 if force else float(data.get("last_synced_at") or 0)
        try:
            entries = await plex_community.fetch_history_since(plex_token, uuid, since_epoch=since)
        except Exception as e:
            log.warning(f"sync_user fetch failed for {user_id}: {e}")
            return 0
        if not entries and data.get("last_synced_at"):
            data["last_synced_at"] = max(data.get("last_synced_at") or 0, time.time())
            save(user_id, data)
            return 0
        added = _merge_entries(data, entries, uuid)
        save(user_id, data)
        if added:
            log.info(f"watch_data: synced {added} new plays for user {user_id}")
        return added


# --- Read helpers (all support optional `since` epoch for date-windowing) ----

def _filtered(plays: list, since: float = 0) -> list:
    if since <= 0:
        return plays
    # Plays are sorted by date ascending; find first index >= since via binary search
    import bisect
    idx = bisect.bisect_left([p["d"] for p in plays], since)
    return plays[idx:]


def watched_movies(user_id: int, since: float = 0) -> set[tuple[str, int]]:
    plays = _filtered(load(user_id).get("plays", []), since)
    return {(p["ti"].lower(), int(p.get("y") or 0)) for p in plays if p.get("t") == "M"}


def started_shows(user_id: int, since: float = 0) -> set[str]:
    plays = _filtered(load(user_id).get("plays", []), since)
    return {p["s"] for p in plays if p.get("t") == "E" and p.get("s")}


def watched_episodes_for_show(user_id: int, show_title: str, since: float = 0) -> set[tuple[int, int]]:
    plays = _filtered(load(user_id).get("plays", []), since)
    show_lower = show_title.lower()
    return {
        (int(p["se"]), int(p["ep"]))
        for p in plays
        if p.get("t") == "E" and (p.get("s") or "").lower() == show_lower
    }


def watched_count_per_season(user_id: int, show_title: str) -> dict[int, int]:
    plays = load(user_id).get("plays", [])
    show_lower = show_title.lower()
    seen: set[tuple[int, int]] = set()
    counts: dict[int, int] = {}
    for p in plays:
        if p.get("t") != "E" or (p.get("s") or "").lower() != show_lower:
            continue
        try:
            season = int(p["se"])
            ep = int(p["ep"])
        except Exception:
            continue
        if (season, ep) in seen:
            continue
        seen.add((season, ep))
        counts[season] = counts.get(season, 0) + 1
    return counts


def has_data(user_id: int) -> bool:
    return bool(load(user_id).get("plays"))


def last_synced_at(user_id: int) -> float:
    return float(load(user_id).get("last_synced_at") or 0)


def top_shows_by_episodes(user_id: int, limit: int = 10, since: float = 0) -> list[dict]:
    plays = _filtered(load(user_id).get("plays", []), since)
    by_show: dict[str, dict] = {}
    for p in plays:
        if p.get("t") != "E" or not p.get("s"):
            continue
        show = p["s"]
        b = by_show.setdefault(show, {"plays": 0, "eps": set(), "lastWatched": 0.0})
        b["plays"] += 1
        try:
            b["eps"].add((int(p["se"]), int(p["ep"])))
        except Exception:
            pass
        if p["d"] > b["lastWatched"]:
            b["lastWatched"] = p["d"]
    rows = [
        {"title": show, "episodesWatched": len(v["eps"]), "plays": v["plays"], "lastWatched": v["lastWatched"]}
        for show, v in by_show.items()
        if v["eps"]
    ]
    rows.sort(key=lambda x: (-x["episodesWatched"], -x["plays"], -x["lastWatched"]))
    return rows[:limit]


def top_movies_by_plays(user_id: int, limit: int = 10, since: float = 0) -> list[dict]:
    plays = _filtered(load(user_id).get("plays", []), since)
    by_movie: dict[tuple[str, int], dict] = {}
    for p in plays:
        if p.get("t") != "M":
            continue
        key = (p["ti"].lower(), int(p.get("y") or 0))
        b = by_movie.setdefault(key, {"title": p["ti"], "year": int(p.get("y") or 0) or None, "plays": 0, "lastWatched": 0.0})
        b["plays"] += 1
        if p["d"] > b["lastWatched"]:
            b["lastWatched"] = p["d"]
    rows = list(by_movie.values())
    rows.sort(key=lambda x: (-x["plays"], -x["lastWatched"], (x["title"] or "").lower()))
    return rows[:limit]


def all_plays(user_id: int, since: float = 0) -> list[dict]:
    """Raw play list (for callers that want to do their own aggregation)."""
    return _filtered(load(user_id).get("plays", []), since)


def streaks(user_id: int, since: float = 0) -> dict:
    """Longest run of consecutive watch days + current active streak (within window)."""
    plays = _filtered(load(user_id).get("plays", []), since)
    if not plays:
        return {"longest": 0, "current": 0, "longestEndDate": 0}
    from datetime import date
    days_seen = sorted({date.fromtimestamp(p["d"]).toordinal() for p in plays if p.get("d")})
    if not days_seen:
        return {"longest": 0, "current": 0, "longestEndDate": 0}
    # Walk runs
    longest_run = 1
    current_run = 1
    longest_end = days_seen[0]
    cur_end = days_seen[0]
    for i in range(1, len(days_seen)):
        if days_seen[i] == days_seen[i - 1] + 1:
            current_run += 1
        else:
            current_run = 1
        cur_end = days_seen[i]
        if current_run > longest_run:
            longest_run = current_run
            longest_end = cur_end
    today = date.today().toordinal()
    active_streak = current_run if (today - days_seen[-1]) <= 1 else 0
    return {
        "longest": longest_run,
        "current": active_streak,
        "longestEndDate": date.fromordinal(longest_end).isoformat(),
    }


def power_day(user_id: int, since: float = 0) -> dict:
    """Single calendar day with the most plays within the window."""
    plays = _filtered(load(user_id).get("plays", []), since)
    if not plays:
        return {"date": "", "seconds": 0, "plays": 0}
    from datetime import date
    by_day: dict[str, dict] = {}
    for p in plays:
        if not p.get("d"):
            continue
        day = date.fromtimestamp(p["d"]).isoformat()
        b = by_day.setdefault(day, {"seconds": 0, "plays": 0})
        b["seconds"] += int(p.get("du") or 0)
        b["plays"] += 1
    if not by_day:
        return {"date": "", "seconds": 0, "plays": 0}
    best_day = max(by_day, key=lambda d: by_day[d]["seconds"])
    return {"date": best_day, "seconds": by_day[best_day]["seconds"], "plays": by_day[best_day]["plays"]}


def day_of_week_breakdown(user_id: int, since: float = 0) -> list[dict]:
    """Total seconds + plays per day-of-week (0=Mon) within the window."""
    plays = _filtered(load(user_id).get("plays", []), since)
    from datetime import date
    buckets = [{"day": i, "seconds": 0, "plays": 0} for i in range(7)]
    for p in plays:
        if not p.get("d"):
            continue
        dow = date.fromtimestamp(p["d"]).weekday()
        buckets[dow]["seconds"] += int(p.get("du") or 0)
        buckets[dow]["plays"] += 1
    return buckets


def hour_of_day_breakdown(user_id: int, since: float = 0) -> list[dict]:
    """Total seconds + plays per hour of day (0-23) within the window."""
    plays = _filtered(load(user_id).get("plays", []), since)
    from datetime import datetime as dt
    buckets = [{"hour": i, "seconds": 0, "plays": 0} for i in range(24)]
    for p in plays:
        if not p.get("d"):
            continue
        h = dt.fromtimestamp(p["d"]).hour
        buckets[h]["seconds"] += int(p.get("du") or 0)
        buckets[h]["plays"] += 1
    return buckets


def comfort_show(user_id: int, since: float = 0) -> dict | None:
    """Show with the highest plays in the window — your go-to rewatcher."""
    plays = _filtered(load(user_id).get("plays", []), since)
    counts: dict[str, dict] = {}
    for p in plays:
        if p.get("t") != "E" or not p.get("s"):
            continue
        c = counts.setdefault(p["s"], {"plays": 0, "seconds": 0, "lastWatched": 0.0})
        c["plays"] += 1
        c["seconds"] += int(p.get("du") or 0)
        if p["d"] > c["lastWatched"]:
            c["lastWatched"] = p["d"]
    if not counts:
        return None
    show = max(counts, key=lambda s: counts[s]["plays"])
    return {"title": show, "plays": counts[show]["plays"], "seconds": counts[show]["seconds"], "lastWatched": counts[show]["lastWatched"]}


def rewatch_ratio(user_id: int, since: float = 0) -> dict:
    """% of plays that are repeat watches within the window."""
    plays = _filtered(load(user_id).get("plays", []), since)
    if not plays:
        return {"firstTime": 0, "rewatches": 0, "ratio": 0}
    # For each unique item, count plays
    item_counts: dict[tuple, int] = {}
    for p in plays:
        if p.get("t") == "M":
            key = ("M", p.get("ti", "").lower(), int(p.get("y") or 0))
        else:
            key = ("E", (p.get("s") or "").lower(), int(p.get("se") or 0), int(p.get("ep") or 0))
        item_counts[key] = item_counts.get(key, 0) + 1
    first_time = sum(1 for c in item_counts.values())  # one "first watch" per unique item
    rewatches = sum(c - 1 for c in item_counts.values() if c > 1)
    total = first_time + rewatches
    return {
        "firstTime": first_time,
        "rewatches": rewatches,
        "ratio": round(100 * rewatches / total, 1) if total else 0,
    }


def cross_server_totals(user_id: int, since: float = 0) -> dict:
    """Aggregate cross-server hours and plays for the given window. since=0 → all-time."""
    plays = _filtered(load(user_id).get("plays", []), since)
    movie_seconds = 0
    movie_plays = 0
    episode_seconds = 0
    episode_plays = 0
    by_show: dict[str, int] = {}
    for p in plays:
        dur = int(p.get("du") or 0)
        if p.get("t") == "M":
            movie_plays += 1
            movie_seconds += dur
        elif p.get("t") == "E":
            episode_plays += 1
            episode_seconds += dur
            show = p.get("s") or ""
            if show and dur:
                by_show[show] = by_show.get(show, 0) + dur
    return {
        "seconds": movie_seconds + episode_seconds,
        "plays": movie_plays + episode_plays,
        "movieSeconds": movie_seconds,
        "moviePlays": movie_plays,
        "episodeSeconds": episode_seconds,
        "episodePlays": episode_plays,
        "byShow": by_show,
    }
