import httpx
from backend.config import SONARR_URL, SONARR_API_KEY


def _headers() -> dict:
    return {"X-Api-Key": SONARR_API_KEY}


async def get(path: str, params: dict | None = None, timeout: int = 30) -> dict | list:
    async with httpx.AsyncClient(timeout=timeout) as c:
        resp = await c.get(f"{SONARR_URL}/api/v3{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def delete(path: str) -> int:
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.delete(f"{SONARR_URL}/api/v3{path}", headers=_headers())
        resp.raise_for_status()
        return resp.status_code


async def post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            f"{SONARR_URL}/api/v3{path}",
            headers={**_headers(), "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def lookup(term: str) -> list:
    return await get("/series/lookup", {"term": term})


async def library() -> list:
    return await get("/series")


async def episodes(series_id: int, season: int | None = None) -> list:
    params: dict = {"seriesId": series_id}
    if season is not None:
        params["seasonNumber"] = season
    return await get("/episode", params)


async def episode_file(file_id: int) -> dict:
    return await get(f"/episodefile/{file_id}")


async def delete_episode_file(file_id: int) -> int:
    return await delete(f"/episodefile/{file_id}")


async def search_episode(episode_id: int) -> dict:
    return await post("/command", {"name": "EpisodeSearch", "episodeIds": [episode_id]})


async def queue(page_size: int = 100) -> dict:
    return await get("/queue", {"pageSize": page_size, "includeEpisode": True})


async def history_for_episode(episode_id: int) -> dict:
    # Sonarr's /history endpoint accepts episodeId (singular); episodeIds is
    # silently ignored, which returns the most recent history across ALL
    # shows — leading us to fail_history the wrong show's release.
    return await get("/history", {
        "episodeId": episode_id, "pageSize": 20,
        "sortKey": "date", "sortDirection": "descending",
    })


async def fail_history(history_id: int):
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            f"{SONARR_URL}/api/v3/history/failed/{history_id}",
            headers=_headers(),
        )
        resp.raise_for_status()


async def search_releases(episode_id: int) -> list:
    return await get("/release", {"episodeId": episode_id}, timeout=120)


async def grab_release(guid: str, indexer_id: int) -> dict:
    return await post("/release", {"guid": guid, "indexerId": indexer_id})
