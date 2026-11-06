"""Bound drafting work and stop waiting when the browser leaves.

Limits are per API process. A deployment with multiple API workers needs a shared
limiter for a single local model server.
"""
import asyncio
from contextlib import contextmanager, suppress
from threading import Lock

from fastapi import HTTPException, Request

_guard = Lock()
_users: set[int] = set()
_local_busy = False


@contextmanager
def claim_draft(user_id: int, local: bool):
    global _local_busy
    with _guard:
        if user_id in _users:
            raise HTTPException(429, "A draft is already being written for you. Wait for it or cancel it before trying again.", headers={"Retry-After": "2"})
        if (local and _local_busy) or len(_users) >= 4:
            raise HTTPException(503, "AI drafting is busy. Please try again in a few seconds.", headers={"Retry-After": "3"})
        _users.add(user_id)
        if local:
            _local_busy = True
    try:
        yield
    finally:
        with _guard:
            _users.discard(user_id)
            if local:
                _local_busy = False


async def wait_for_draft(request: Request, operation, timeout_seconds: float):
    """Cancel the provider coroutine on disconnect, deadline or parent cancellation."""
    task = asyncio.create_task(operation)
    try:
        async with asyncio.timeout(timeout_seconds):
            while not task.done():
                await asyncio.wait({task}, timeout=0.2)
                if not task.done() and await request.is_disconnected():
                    raise HTTPException(499, "Draft request cancelled.")
            return await task
    except TimeoutError:
        raise HTTPException(504, "AI drafting took too long. Your email is unchanged; please try again.") from None
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
