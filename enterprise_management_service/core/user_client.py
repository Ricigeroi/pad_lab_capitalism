import httpx
from core.config import settings


async def fetch_user(user_id: int) -> dict | None:
    """
    Fetch a user profile from user_management_service.
    Returns the JSON dict on success, or None if the user was not found / service unreachable.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.USER_SERVICE_URL}/user/{user_id}")
            if resp.status_code == 200:
                return resp.json()
    except httpx.RequestError:
        pass
    return None


async def fetch_users(user_ids: list[int]) -> dict[int, dict]:
    """
    Fetch multiple user profiles concurrently.
    Returns a mapping of user_id -> user dict for every id that was found.
    """
    import asyncio

    async def _get(uid: int) -> tuple[int, dict | None]:
        return uid, await fetch_user(uid)

    results = await asyncio.gather(*[_get(uid) for uid in user_ids])
    return {uid: data for uid, data in results if data is not None}
