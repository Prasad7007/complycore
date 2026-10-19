import asyncio
from typing import Any


_review_comment_subscribers: dict[str, list[asyncio.Queue]] = {}
_review_comment_lock = asyncio.Lock()

_notification_subscribers: dict[str, list[asyncio.Queue]] = {}
_notification_lock = asyncio.Lock()


async def subscribe_review_comments(review_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    async with _review_comment_lock:
        _review_comment_subscribers.setdefault(review_id, []).append(queue)
    return queue


async def unsubscribe_review_comments(review_id: str, queue: asyncio.Queue) -> None:
    async with _review_comment_lock:
        subscribers = _review_comment_subscribers.get(review_id) or []
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            _review_comment_subscribers.pop(review_id, None)


async def publish_review_comment(review_id: str, payload: dict[str, Any]) -> int:
    async with _review_comment_lock:
        subscribers = list(_review_comment_subscribers.get(review_id) or [])

    delivered = 0
    for queue in subscribers:
        try:
            queue.put_nowait(payload)
            delivered += 1
        except asyncio.QueueFull:
            # Drop oldest event to favor latest updates.
            try:
                queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(payload)
                delivered += 1
            except Exception:
                pass
    return delivered


async def subscribe_notifications(user_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    async with _notification_lock:
        _notification_subscribers.setdefault(user_id, []).append(queue)
    return queue


async def unsubscribe_notifications(user_id: str, queue: asyncio.Queue) -> None:
    async with _notification_lock:
        subscribers = _notification_subscribers.get(user_id) or []
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            _notification_subscribers.pop(user_id, None)


async def publish_notification(user_id: str, payload: dict[str, Any]) -> int:
    async with _notification_lock:
        subscribers = list(_notification_subscribers.get(user_id) or [])

    delivered = 0
    for queue in subscribers:
        try:
            queue.put_nowait(payload)
            delivered += 1
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(payload)
                delivered += 1
            except Exception:
                pass
    return delivered


async def check_recent_notification_exists(
    db,
    user_id: str,
    title: str,
    message: str,
    reference_id: str,
    seconds: int = 5
) -> bool:
    """Check if an identical notification was created for this user in the last `seconds` seconds."""
    return await db.fetchval(
        """
        SELECT EXISTS (
            SELECT 1 FROM notifications
            WHERE user_id = $1
              AND title = $2
              AND message = $3
              AND reference_id = $4::uuid
              AND created_at >= (NOW() AT TIME ZONE 'utc') - ($5 * INTERVAL '1 second')
        )
        """,
        user_id,
        title,
        message,
        reference_id,
        seconds,
    )

