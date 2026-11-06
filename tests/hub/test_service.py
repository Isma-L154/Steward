import asyncio
import copy
from datetime import UTC, datetime, timedelta

import pytest

from steward.dependabot.decision import MAJOR_READY
from steward.github.http import GitHubError
from steward.github.models import RepoRef
from steward.hub.service import SCHEMA_VERSION, SNAPSHOT_TTL, HubService
from steward.hub.snapshot import DEPENDABOT_AUTHOR, HubRepo, OpenPull
from tests.hub.fakes import Clock, CountingSource, FakeHubStore

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _service(
    source: CountingSource, store: FakeHubStore | None = None, clock: Clock | None = None
) -> HubService:
    return HubService(source, store or FakeHubStore(), clock or Clock(T0), "app-steward")


def test_ttl_is_five_minutes() -> None:
    assert timedelta(minutes=5) == SNAPSHOT_TTL


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


async def test_report_is_cached_for_five_minutes() -> None:
    source, clock = CountingSource(), Clock(T0)
    service = _service(source, clock=clock)
    first = await service.report()
    clock.now = T0 + timedelta(minutes=4, seconds=59)
    assert await service.report() == first
    assert source.calls == 1
    clock.now = T0 + timedelta(minutes=5)
    await service.report()
    assert source.calls == 2


@pytest.mark.parametrize("first_key", ["health", "report"])
async def test_one_refresh_serves_both(first_key: str) -> None:
    source, clock = CountingSource(), Clock(T0)
    service = _service(source, clock=clock)
    first = await getattr(service, first_key)()
    clock.now = T0 + timedelta(minutes=4, seconds=59)
    other_key = "report" if first_key == "health" else "health"
    other = await getattr(service, other_key)()
    assert source.calls == 1
    assert first["generated_at"] == other["generated_at"] == "2026-10-19T12:00:00Z"
    if other_key == "health":
        assert other["repositories"][0]["repo"] == "o/a"
    else:
        assert other["unknown"] == ["o/a"]


async def test_concurrent_health_and_report_calls_refresh_once() -> None:
    gate = asyncio.Event()
    source = CountingSource(gate=gate)
    service = _service(source)
    calls = [
        asyncio.create_task(method())
        for method in (service.health, service.report, service.report, service.health)
    ]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*calls)
    assert source.calls == 1
    assert results[0] == results[3]
    assert results[1] == results[2]
    assert results[0]["generated_at"] == results[1]["generated_at"]


async def test_closed_dependabot_pull_leaves_report_after_five_minutes() -> None:
    repo = RepoRef("o", "a")
    pull = OpenPull(12, "Bump package", DEPENDABOT_AUTHOR, frozenset({MAJOR_READY}))
    source = CountingSource(repos=[HubRepo(repo, pulls=(pull,), standards_issues=())])
    clock = Clock(T0)
    service = _service(source, clock=clock)
    first = await service.report()
    assert first["major_ready"] == [
        {
            "repo": "o/a",
            "number": 12,
            "title": "Bump package",
            "url": "https://github.com/o/a/pull/12",
        }
    ]
    source.repos = [HubRepo(repo, pulls=(), standards_issues=())]
    clock.now = T0 + timedelta(minutes=4, seconds=59)
    assert (await service.report())["major_ready"] == first["major_ready"]
    assert source.calls == 1
    clock.now = T0 + timedelta(minutes=5)
    assert (await service.report())["major_ready"] == []
    assert source.calls == 2


@pytest.mark.parametrize("fetched_at", ["2026-10-19T11:54:59Z", "2026-10-19T13:00:00Z", None])
async def test_stale_or_legacy_report_is_refreshed(fetched_at: str | None) -> None:
    stored: dict[str, object] = {"schema": SCHEMA_VERSION, "body": {"old": 1}}
    if fetched_at is not None:
        stored["fetched_at"] = fetched_at
    store = FakeHubStore({"report": stored})
    source = CountingSource()
    body = await _service(source, store).report()
    assert source.calls == 1
    assert "old" not in body
    assert body["generated_at"] == "2026-10-19T12:00:00Z"


async def test_failed_report_refresh_raises_and_leaves_storage_unchanged() -> None:
    stale = {
        "schema": SCHEMA_VERSION,
        "fetched_at": "2026-10-19T11:00:00Z",
        "body": {"generated_at": "2026-10-19T11:00:00Z", "major_ready": []},
    }
    store = FakeHubStore({"report": stale, "health": copy.deepcopy(stale)})
    previous = copy.deepcopy(store.values)
    source = CountingSource(fail=True)
    with pytest.raises(GitHubError):
        await _service(source, store).report()
    assert source.calls == 1
    assert store.values == previous


@pytest.mark.parametrize("key", ["health", "report"])
async def test_refresh_stores_both_with_one_timestamp_and_schema(key: str) -> None:
    source, store = CountingSource(), FakeHubStore()
    clock_calls = 0

    # Each reading is a second later, so two readings would show up as two timestamps.
    def clock() -> datetime:
        nonlocal clock_calls
        now = T0 + timedelta(seconds=clock_calls)
        clock_calls += 1
        return now

    service = HubService(source, store, clock, "app-steward")
    body = await getattr(service, key)()
    assert source.calls == 1
    assert store.values.keys() == {"health", "report"}
    for cached in store.values.values():
        assert cached["schema"] == SCHEMA_VERSION
        assert cached["fetched_at"] == "2026-10-19T12:00:00Z"
        assert cached["body"]["generated_at"] == cached["fetched_at"]
    assert store.values[key]["body"] == body


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


@pytest.mark.parametrize("schema", [None, SCHEMA_VERSION - 1, SCHEMA_VERSION + 1, "1"])
async def test_fresh_report_of_another_schema_is_refreshed(schema: object) -> None:
    stored: dict[str, object] = {"fetched_at": "2026-10-19T11:58:00Z", "body": {"old": 1}}
    if schema is not None:
        stored["schema"] = schema
    store = FakeHubStore({"report": stored})
    source = CountingSource()
    body = await _service(source, store).report()
    assert source.calls == 1
    assert "old" not in body
    assert store.values["report"]["schema"] == SCHEMA_VERSION


async def test_fresh_report_of_this_schema_is_served() -> None:
    stored = {"schema": SCHEMA_VERSION, "fetched_at": "2026-10-19T11:58:00Z", "body": {"old": 1}}
    source = CountingSource()
    assert await _service(source, FakeHubStore({"report": stored})).report() == {"old": 1}
    assert source.calls == 0
