"""Cancellation and admission tests need no database or real model server."""
import asyncio

import pytest
from fastapi import HTTPException

from app.draft_execution import claim_draft, wait_for_draft


class Browser:
    def __init__(self, disconnected=False):
        self.disconnected = disconnected

    async def is_disconnected(self):
        return self.disconnected


def test_duplicate_user_is_refused_and_slot_is_released():
    with claim_draft(501, False):
        with pytest.raises(HTTPException) as rejected:
            with claim_draft(501, False):
                pytest.fail('Duplicate request admitted')
        assert rejected.value.status_code == 429
        assert rejected.value.headers['Retry-After'] == '2'
    with claim_draft(501, False):
        pass


def test_local_model_does_not_build_an_unbounded_queue():
    with claim_draft(501, True):
        with pytest.raises(HTTPException) as rejected:
            with claim_draft(502, True):
                pytest.fail('Overlapping local request admitted')
        assert rejected.value.status_code == 503
        # Hosted drafting uses a different provider and is not blocked by the local model.
        with claim_draft(502, False):
            pass
    with claim_draft(502, True):
        pass


def test_failed_operation_releases_admission_slot():
    with pytest.raises(ValueError):
        with claim_draft(501, True):
            raise ValueError('Synthetic failure')
    with claim_draft(501, True):
        pass


def test_completed_draft_is_returned():
    async def scenario():
        async def operation():
            return {'subject': 'A draft'}
        assert await wait_for_draft(Browser(), operation(), 1) == {'subject': 'A draft'}
    asyncio.run(scenario())


@pytest.mark.parametrize('disconnected,timeout,expected', [(True, 1, 499), (False, .01, 504)])
def test_disconnect_or_deadline_cancels_provider(disconnected, timeout, expected):
    async def scenario():
        cancelled = asyncio.Event()
        async def operation():
            try:
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        with pytest.raises(HTTPException) as failed:
            await wait_for_draft(Browser(disconnected), operation(), timeout)
        assert failed.value.status_code == expected
        assert cancelled.is_set()
    asyncio.run(scenario())


def test_parent_cancellation_also_stops_provider():
    async def scenario():
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def operation():
            try:
                started.set()
                await asyncio.sleep(60)
            finally:
                cancelled.set()
        task = asyncio.create_task(wait_for_draft(Browser(), operation(), 1))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
    asyncio.run(scenario())
