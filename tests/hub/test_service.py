import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest

from steward.github.http import GitHubError
from steward.hub.service import HEALTH_TTL, SCHEMA_VERSION, HubService
from tests.hub.fakes import Clock, CountingSource, FakeHubStore

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _service(
    source: CountingSource, store: FakeHubStore | None = None, clock: Clock | None = None
) -> HubService:
    return HubService(source, store or FakeHubStore(), clock or Clock(T0), "app-steward")


def test_ttl_is_five_minutes() -> None:
    assert timedelta(minutes=5) == HEALTH_TTL


async def test_health_is_cached_for_five_minutes() -> None:
    source, clock = CountingSource(), Clock(T0)
    service = _service(source, clock=clock)
    first = await service.health()
    clock.now = T0 + timedelta(minutes=4, seconds=59)
    assert await service.health() == first
    assert source.calls == 1
    clock.now = T0 + timedelta(minutes=5)
    await service.health()
    assert source.calls == 2


async def test_concurrent_health_calls_refresh_once() -> None:
    gate = asyncio.Event()
    source = CountingSource(gate=gate)
    service = _service(source)
    calls = [asyncio.create_task(service.health()) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*calls)
    assert source.calls == 1
    assert all(result == results[0] for result in results)


async def test_future_stamped_cache_is_stale() -> None:
    future = {"schema": SCHEMA_VERSION, "fetched_at": "2026-10-19T13:00:00Z", "body": {"old": 1}}
    store = FakeHubStore({"health": future})
    source = CountingSource()
    body = await _service(source, store).health()
    assert source.calls == 1
    assert "old" not in body


async def test_failed_refresh_raises_and_keeps_no_stale_answer() -> None:
    stale = {"fetched_at": "2026-10-19T11:00:00Z", "body": {"old": 1}}
    store = FakeHubStore({"health": stale})
    with pytest.raises(GitHubError):
        await _service(CountingSource(fail=True), store).health()


async def test_report_built_once_when_none_stored() -> None:
    source = CountingSource()
    service = _service(source)
    first = await service.report()
    assert await service.report() == first
    assert source.calls == 1
    assert first["generated_at"] == "2026-10-19T12:00:00Z"


async def test_build_report_stores_only_on_success() -> None:
    previous = {"generated_at": "2026-10-12T06:03:00Z", "major_ready": []}
    store = FakeHubStore({"report": {"schema": SCHEMA_VERSION, "body": copy.deepcopy(previous)}})
    with pytest.raises(GitHubError):
        await _service(CountingSource(fail=True), store).build_report()
    assert store.values["report"]["body"] == previous
    assert await _service(CountingSource(fail=True), store).report() == previous


async def test_build_report_also_refreshes_health() -> None:
    source = CountingSource()
    service = _service(source)
    await service.build_report()
    await service.health()
    assert source.calls == 1


@pytest.mark.parametrize("schema", [None, SCHEMA_VERSION - 1, SCHEMA_VERSION + 1, "1"])
async def test_fresh_health_of_another_schema_is_refreshed(schema: object) -> None:
    stored: dict[str, object] = {"fetched_at": "2026-10-19T11:58:00Z", "body": {"old": 1}}
    if schema is not None:
        stored["schema"] = schema
    store = FakeHubStore({"health": stored})
    source = CountingSource()
    body = await _service(source, store).health()
    assert source.calls == 1
    assert "old" not in body
    assert store.values["health"]["schema"] == SCHEMA_VERSION


async def test_fresh_health_of_this_schema_is_served() -> None:
    stored = {"schema": SCHEMA_VERSION, "fetched_at": "2026-10-19T11:58:00Z", "body": {"old": 1}}
    source = CountingSource()
    assert await _service(source, FakeHubStore({"health": stored})).health() == {"old": 1}
    assert source.calls == 0


@pytest.mark.parametrize(
    "stored",
    [
        {"generated_at": "2026-10-12T06:03:00Z", "major_ready": []},
        {"schema": SCHEMA_VERSION - 1, "body": {"generated_at": "2026-10-12T06:03:00Z"}},
    ],
)
async def test_report_of_another_schema_is_rebuilt_once(stored: dict[str, object]) -> None:
    store = FakeHubStore({"report": stored})
    source = CountingSource()
    service = _service(source, store)
    first = await service.report()
    assert first["generated_at"] == "2026-10-19T12:00:00Z"
    assert await service.report() == first
    assert source.calls == 1
    assert store.values["report"] == {"schema": SCHEMA_VERSION, "body": first}
