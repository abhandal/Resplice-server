import httpx
from backend.config import RADARR_URL, RADARR_API_KEY


def _headers() -> dict:
    return {"X-Api-Key": RADARR_API_KEY}


async def get(path: str, params: dict | None = None, timeout: int = 30) -> dict | list:
    async with httpx.AsyncClient(timeout=timeout) as c:
        resp = await c.get(f"{RADARR_URL}/api/v3{path}", headers=_headers(), params=params)
        resp.raise_for_status()
        return resp.json()


async def delete(path: str) -> int:
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.delete(f"{RADARR_URL}/api/v3{path}", headers=_headers())
        resp.raise_for_status()
        return resp.status_code


async def post(path: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            f"{RADARR_URL}/api/v3{path}",
            headers={**_headers(), "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def lookup(term: str) -> list:
    return await get("/movie/lookup", {"term": term})


async def library() -> list:
    return await get("/movie")


async def movie(movie_id: int) -> dict:
    return await get(f"/movie/{movie_id}")


async def movie_file(file_id: int) -> dict:
    return await get(f"/moviefile/{file_id}")


async def delete_movie_file(file_id: int) -> int:
    return await delete(f"/moviefile/{file_id}")


async def search_movie(movie_id: int) -> dict:
    return await post("/command", {"name": "MoviesSearch", "movieIds": [movie_id]})


async def queue(page_size: int = 100) -> dict:
    return await get("/queue", {"pageSize": page_size})


async def history_for_movie(movie_id: int) -> list:
    return await get("/history/movie", {
        "movieId": movie_id, "pageSize": 20,
        "sortKey": "date", "sortDirection": "descending",
    })


async def fail_history(history_id: int):
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            f"{RADARR_URL}/api/v3/history/failed/{history_id}",
            headers=_headers(),
        )
        resp.raise_for_status()


async def search_releases(movie_id: int) -> list:
    return await get("/release", {"movieId": movie_id}, timeout=120)


async def grab_release(guid: str, indexer_id: int) -> dict:
    return await post("/release", {"guid": guid, "indexerId": indexer_id})
