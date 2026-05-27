# TT-137: Clean up pytest warnings produced by pre-push hook — Implementation Plan

> **Jira:** [TT-137](https://mandeng.atlassian.net/browse/TT-137)
> **Branch:** `feature/TT-137-pytest-warnings-cleanup`
> **Status:** Draft 2026-05-09

## Goal

Make the pytest warnings summary empty (or contain only warnings unrelated to this ticket) when running the pre-push gate, so future warnings have signal. Fix root causes in test setup — do **not** suppress with `filterwarnings`.

## Background

`git push` triggers `.githooks/pre-push` → `pytest`. All 943 tests pass, but two distinct warning categories appear in the summary:

1. **Pydantic serializer warnings** (`unit_tests/accounts/test_fill_monitor.py`) — 7 tests in `TestMonitorFillsForEntryCredits` warn about `order_type` / `time_in_force` / `filled_at` not matching their declared enum / datetime types.
2. **Unawaited coroutine** (`unit_tests/signal_service/test_runner.py::test_runner_start_connects_and_subscribes`) — `RuntimeWarning: coroutine 'RedisSubscription.listener' was never awaited`.

## Category 1 — Pydantic serializer warnings

### Root cause

The factory functions in `unit_tests/accounts/test_fill_monitor.py` use `model_construct()` (which bypasses validation) and pass raw strings for fields whose declared types are enums or `datetime`:

```python
# unit_tests/accounts/test_fill_monitor.py:37-45
def make_order(...) -> PlacedOrder:
    return PlacedOrder.model_construct(
        ...
        order_type="Limit",        # field type: OrderType enum
        time_in_force="Day",       # field type: TimeInForce enum
        ...
    )

# unit_tests/accounts/test_fill_monitor.py:48-58
def make_fill(...) -> OrderFill:
    return OrderFill.model_construct(
        ...
        filled_at="2026-03-16T20:00:00Z",  # field type: datetime
    )
```

Source-of-truth declarations:
- `src/tastytrade/accounts/models.py:797` — `class TimeInForce(str, Enum)` with `DAY = "Day"`
- `src/tastytrade/accounts/models.py:805` — `class OrderType(str, Enum)` with `LIMIT = "Limit"`
- `src/tastytrade/accounts/models.py:821` — `filled_at: datetime`

`model_construct()` skips coercion, so the in-memory instance literally stores `str` where the schema expects enum / datetime. When `TestMonitorFillsForEntryCredits` later calls `order.model_dump_json(by_alias=True)` (at `unit_tests/accounts/test_fill_monitor.py:200`) Pydantic's serializer notices the type mismatch and emits `PydanticSerializationUnexpectedValue`.

### Fix

Replace the raw string arguments with the typed values the schema expects:

| Argument | Current | Replace with |
|---|---|---|
| `order_type` | `"Limit"` | `OrderType.LIMIT` |
| `time_in_force` | `"Day"` | `TimeInForce.DAY` |
| `filled_at` | `"2026-03-16T20:00:00Z"` | `datetime(2026, 3, 16, 20, 0, 0, tzinfo=timezone.utc)` |

Add the missing imports at the top of the test file:
- `from datetime import datetime, timezone`
- Extend the existing `from tastytrade.accounts.models import …` to include `OrderType` and `TimeInForce`

Both `OrderType` and `TimeInForce` inherit from `str, Enum`, so the wire serialization (string `"Limit"`, `"Day"`) is unchanged. Existing assertions on field equality also remain valid because of `str` mixin equality.

### Files changed

- `unit_tests/accounts/test_fill_monitor.py` — update `make_order` and `make_fill` factory functions and imports. No production code is touched.

## Category 2 — Unawaited coroutine in `test_runner.py`

### Root cause (hypothesis)

`unit_tests/signal_service/test_runner.py:13-22` builds the `runner` fixture with `subscription=AsyncMock()` (no `spec`). When `runner.start()` is called the test patches `asyncio.Event` to raise `CancelledError`, so the awaited bodies of `subscription.connect()` and `subscription.subscribe(...)` are AsyncMock awaitables — those should be fine on their own.

The warning text is `coroutine 'RedisSubscription.listener' was never awaited` and the traceback points into `unittest/mock.py`. That tells us a real `RedisSubscription.listener` coroutine object is being instantiated inside `mock`'s spec / attribute introspection path — most likely because something accesses an attribute on the AsyncMock with the name `listener`, and `AsyncMock` falls back to `RedisSubscription.listener` (the unbound coroutine function on the class) when generating its async-child mock.

The implementer should confirm exactly where the coroutine is being created. Two likely diagnostics:

1. Run the single test with `python -W error::RuntimeWarning -X tracemalloc -m pytest unit_tests/signal_service/test_runner.py::test_runner_start_connects_and_subscribes -p no:cacheprovider` and inspect the traceback.
2. Inspect whether AsyncMock's `_get_child_mock` / spec inference is creating the coroutine when `RedisSubscription` is implied as the spec via type annotation (it normally is *not* — but this is the most likely path worth verifying).

### Fix (provisional, pending diagnostic confirmation)

Most likely the cleanest fix is one of:

- **Option A — explicit spec with safer member set.** Use `AsyncMock(spec=RedisSubscription)` *and* explicitly stub `connect`, `subscribe`, `close` with `AsyncMock()`. This pre-creates the methods the test actually calls and keeps mock from materializing `listener`.
- **Option B — narrow spec to the protocol.** `connections/subscription.py:47` defines `RedisSubscriptionStore(SubscriptionStore)` — there's a Protocol in the codebase that does *not* include `listener`. If `EngineRunner` only needs the Protocol surface, `spec=SubscriptionStore` (or whatever the public protocol is) avoids exposing `listener` entirely.
- **Option C — explicit per-method mocks.** Construct `subscription = MagicMock()` and set `subscription.connect = AsyncMock()`, `subscription.subscribe = AsyncMock()`, `subscription.close = AsyncMock()` directly.

The implementer should pick the option that does not introduce a real `RedisSubscription` import side effect into the test (the test should remain fast and Redis-free). After the fix, `assert_awaited_once_with(...)` calls in the test must still work.

**Out of scope:** Suppressing `filterwarnings("ignore::RuntimeWarning")` in `pytest.ini` / `pyproject.toml` — explicitly forbidden by the ticket AC.

### Files changed

- `unit_tests/signal_service/test_runner.py` — adjust `runner` and `sink_runner` fixtures (and the inline runner construction in `test_runner_start_subscribes_multiple_channels`) to whichever fix Option A/B/C the diagnostic confirms. No production code is touched.

## Verification

For each acceptance criterion:

```bash
# AC1 — no Pydantic serializer warnings in fill monitor tests
uv run pytest unit_tests/accounts/test_fill_monitor.py -W error::UserWarning -v

# AC2 — no unawaited-coroutine warnings in runner tests
uv run pytest unit_tests/signal_service/test_runner.py -W error::RuntimeWarning -v

# AC3 — full suite warnings summary is empty (or unrelated)
uv run pytest 2>&1 | sed -n '/warnings summary/,/=====/p'
```

## Risk

Low. Test-only changes:
- Category 1 swaps strings for typed values that serialize to identical wire form.
- Category 2 is a mock-fixture refinement; production code paths are not exercised differently.

The only regression risk is in Category 2: if the new spec is too narrow, tests that incidentally relied on AsyncMock's permissive attribute access could fail. Run the full `unit_tests/signal_service/` directory, not just the one file, after the fix.

## Out of Scope

- The `tracemalloc` hint and the GitHub Dependabot vulnerability count printed by `git push` (these are not pytest warnings).
- Any production-code change to `OrderFill`, `PlacedOrder`, `EngineRunner`, or `RedisSubscription`.
- Suppressing warnings via `filterwarnings`.

## Build Sequence

1. Diagnose Category 2: run the failing test under `-W error::RuntimeWarning` with tracemalloc to confirm the coroutine-creation path. Pick fix option A/B/C.
2. Apply Category 1 fix (factory functions in `test_fill_monitor.py`).
3. Apply Category 2 fix (fixtures in `test_runner.py`).
4. Run AC1, AC2, AC3 verification commands above.
5. `uv run pyright` and `uv run ruff check` clean.
6. Open PR with the captured "warnings summary empty" output as functional evidence.
