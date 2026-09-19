"""Plex Community GraphQL — cross-server watch history per user.

Plex's cloud sync exposes a per-account watch history at https://community.plex.tv/api,
which includes plays from any server the account watched on (including Plex Discover).
We use it as the canonical source of truth when a user's plex_token is available;
otherwise we fall back to local Tautulli history.
"""

import logging
from datetime import datetime
from typing import Iterator

import httpx

log = logging.getLogger("plex-support.plex_community")

ENDPOINT = "https://community.plex.tv/api"

_QUERY_HISTORY = """
query History($id: ID!, $first: PaginationInt, $after: String) {
  user(id: $id) {
    watchHistory(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        date
        metadataItem {
          index
          title
          type
          year
          duration
          parent { title index }
          grandparent { title }
        }
      }
    }
  }
}
"""


def _parse_iso(date_str: str) -> float:
    """Plex returns ISO timestamps like '2026-05-01T14:11:38.000Z'. Return epoch seconds."""
    if not date_str:
        return 0
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


async def _post(token: str, query: str, variables: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            ENDPOINT,
            headers={"X-Plex-Token": token, "Content-Type": "application/json"},
            json={"query": query, "variables": variables},
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Plex Community GraphQL errors: {data['errors']}")
        return data.get("data") or {}


async def fetch_history_since(
    token: str, uuid: str, since_epoch: float = 0, page_size: int = 100, max_pages: int | None = None,
) -> list[dict]:
    """Walk paginated watch history (newest-first) and return every entry strictly newer
    than `since_epoch`. Stops when an older entry is hit (saves pages on incremental sync).

    For the initial backfill (since_epoch=0) we walk to the end — accounts with long
    histories can have 10K+ entries. For incremental syncs the early-exit on old entries
    keeps it cheap regardless of the cap.

    Returns a list of normalized entries:
        {"date": epoch, "type": "EPISODE"|"MOVIE", "title": str, "year": int|None,
         "season": int|None, "episode": int|None, "show": str|None}
    """
    if max_pages is None:
        max_pages = 1000 if since_epoch == 0 else 50
    out: list[dict] = []
    after: str | None = None
    for _ in range(max_pages):
        variables: dict = {"id": uuid, "first": page_size}
        if after:
            variables["after"] = after
        try:
            data = await _post(token, _QUERY_HISTORY, variables)
        except Exception as e:
            log.warning(f"Plex Community history fetch failed for uuid={uuid}: {e}")
            return out

        wh = ((data.get("user") or {}).get("watchHistory") or {})
        nodes = wh.get("nodes", [])
        if not nodes:
            break

        hit_old = False
        for n in nodes:
            d = _parse_iso(n.get("date") or "")
            if since_epoch and d <= since_epoch:
                hit_old = True
                continue
            m = n.get("metadataItem") or {}
            mtype = (m.get("type") or "").upper()
            duration_ms = m.get("duration") or 0
            try:
                duration_s = int(int(duration_ms) / 1000)
            except (TypeError, ValueError):
                duration_s = 0
            entry = {
                "date": d,
                "type": mtype,
                "title": m.get("title") or "",
                "year": m.get("year"),
                "season": (m.get("parent") or {}).get("index"),
                "episode": m.get("index") if mtype == "EPISODE" else None,
                "show": (m.get("grandparent") or {}).get("title"),
                "duration": duration_s,
            }
            out.append(entry)

        page_info = wh.get("pageInfo") or {}
        if hit_old:
            break  # everything beyond is older than since_epoch
        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")

    return out


def iter_episodes(entries: list[dict]) -> Iterator[dict]:
    for e in entries:
        if e.get("type") == "EPISODE":
            yield e


def iter_movies(entries: list[dict]) -> Iterator[dict]:
    for e in entries:
        if e.get("type") == "MOVIE":
            yield e
