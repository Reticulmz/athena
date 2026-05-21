"""Redis async client factory.

Creates a redis.asyncio.Redis client for connecting to a Redis instance.
"""

from redis.asyncio import Redis


def create_redis_client(redis_url: str) -> Redis:
    """Create an async Redis client from a URL.

    Args:
        redis_url: Redis connection URL (e.g. ``redis://localhost:6379``).

    Returns:
        An async Redis client ready for use.
    """
    return Redis.from_url(redis_url)  # pyright: ignore[reportUnknownMemberType]
