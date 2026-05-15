# Multi-Account Pinterest Refactor — File-by-File Diff Plan

**Status:** PLANNING (no code touched yet)
**Author:** Claude Code session 2026-05-03
**Goal:** Run multiple independent Pinterest pipelines in parallel, each owning its own Pinterest account, Firefox profile, credentials, rate-limit budget, and job queue partition. Today the system is hard-wired to one account (`pinterest_rida_v7`), and parallel execution corrupts the shared profile.

---

## Context

The current scaling ceiling is **1 article cycle at a time** because every Pinterest interaction collides on a single Firefox profile, single credential pair, and a global `taskkill /F /IM firefox.exe`. To scale to N pinterest accounts (e.g. one per niche, or one for content + one for harvesting), the code needs five clean partitions per account: **session dir, credentials, rate budget, job queue lane, login state**.

This plan keeps the existing single-account flow working unchanged — multi-account is an additive layer. The default account is `rida` (today's `pinterest_rida_v7`); adding a second account is a config-only operation once the refactor lands.

---

## Current state (where it hurts)

| Concern | File:line | Today |
|---|---|---|
| Session dir name | `pinterest_automation/config.py:49` | `session_name: str = "pinterest_rida_v7"` — single string baked into `BrowserConfig` |
| Credentials | `pinterest_automation/config.py:99-101` | reads only `PINTEREST_EMAIL` / `PINTEREST_PASSWORD` |
| MCP upload tool | `rankstein_mcp_server.py:1139` | `session_dir = PROJECT_ROOT / "data" / "sessions" / "pinterest_rida_v7"` — literal string |
| MCP relogin | `rankstein_mcp_server.py:2256-2261`, `2250-2251` | hard-coded `{uploader, harvester, remasterer}` dict, single env-var pair |
| Firefox lock kill | `pinterest_automation/browser_utils.py:90-91` | `taskkill /F /IM firefox.exe` — nukes EVERY Firefox process on the machine, including sibling pipelines |
| Rate limiter | `pinterest_automation/rate_limiter.py:17-153` | per-process singleton, partitioned by `operation` string only — two pipelines pointing at the same account would each get full budget and trip Pinterest's abuse heuristics |
| Job queue dispatch | `pinterest_automation/job_queue.py` (SQLite) | DB is multi-reader, but the supervisor pulls jobs without an account filter |
| Self-healing model | `pinterest_automation/config.py:61` | `llm_model: str = "gemini-3.1-pro"` — also broken (404), unrelated bug surfaced during this audit |

Two duplicate Firefox-kill helpers still exist (`browser_utils.py:71` and `rankstein_mcp_server.py:2031`). The plan unifies them as part of step 4 instead of leaving the drift.

---

## Proposed architecture

**One concept per partition: `account_handle`.** A short string (`rida`, `alt1`, `niche_postres`) that tags every account-scoped resource. All five partitions key off it:

```
data/accounts.json                          ← roster (handle → metadata)
data/sessions/pinterest_<handle>/           ← Firefox profile (one per handle)
.env                                        ← PINTEREST_EMAIL_<HANDLE>, PINTEREST_PASSWORD_<HANDLE>
RateLimiter._buckets[handle]                ← per-account budget
JobQueue rows have account_handle column    ← dispatcher pulls with WHERE handle=?
```

Single-account behavior is preserved by treating absent handle args as `default_handle` (configurable, ships as `rida` for backward compat with existing session dir + env var names).

### Account roster format

`data/accounts.json`:
```json
{
  "default_handle": "rida",
  "accounts": [
    {
      "handle": "rida",
      "display_name": "Receta Dolce",
      "session_dir": "data/sessions/pinterest_rida_v7",
      "email_env": "PINTEREST_EMAIL",
      "password_env": "PINTEREST_PASSWORD",
      "boards_default": "Recetas Españolas",
      "niches": ["postres", "carnes", "pescados", "ensaladas", "aperitivos"],
      "max_pins_per_day": 300
    },
    {
      "handle": "alt1",
      "display_name": "Receta Dolce Postres",
      "session_dir": "data/sessions/pinterest_alt1",
      "email_env": "PINTEREST_EMAIL_ALT1",
      "password_env": "PINTEREST_PASSWORD_ALT1",
      "boards_default": "Postres Premium",
      "niches": ["postres"],
      "max_pins_per_day": 300
    }
  ]
}
```

The legacy single-account env vars (`PINTEREST_EMAIL` / `PINTEREST_PASSWORD`) keep working because `rida.email_env` points at them.

---

## File-by-file diff

### 1. New file — `pinterest_automation/account.py` (~120 LOC)

Owns the roster lookup. All other code reaches accounts through this module so the format can evolve without rippling.

```python
@dataclass(frozen=True)
class PinterestAccount:
    handle: str
    display_name: str
    session_dir: Path           # absolute, resolved
    email: str                  # resolved from env at load
    password: str
    boards_default: str
    niches: tuple[str, ...]
    max_pins_per_day: int

class AccountRegistry:
    def __init__(self, roster_path: Path = DATA_DIR / "accounts.json"): ...
    @property
    def default(self) -> PinterestAccount: ...
    def get(self, handle: str | None) -> PinterestAccount:
        """handle=None returns default. Raises KeyError on unknown."""
    def all(self) -> list[PinterestAccount]: ...
    def for_niche(self, niche: str) -> PinterestAccount:
        """Round-robin among accounts whose niches match. Falls back to default."""

def get_registry() -> AccountRegistry:  # cached singleton
```

If `accounts.json` is missing, `AccountRegistry.__init__` synthesises a single-account roster from the legacy `PINTEREST_EMAIL`/`PINTEREST_PASSWORD` env vars and `BrowserConfig.session_name` — preserving today's behavior with zero config files added.

---

### 2. `pinterest_automation/config.py` — 3 small edits

**Line 49** (today):
```python
session_name: str = "pinterest_rida_v7"
```
**After:** delete the field. `BrowserConfig` no longer carries a session name; the resolved name comes from `PinterestAccount.session_dir` (which is per-handle).

**Line 95-105** (`PinterestCredentials` dataclass): keep but mark deprecated. New code reads `PinterestAccount.email/password`. The dataclass continues to populate from `PINTEREST_EMAIL`/`PINTEREST_PASSWORD` so anything still importing `get_config().credentials` works for the default account.

**Line 61** (unrelated cleanup, bundled in this PR):
```python
llm_model: str = "gemini-3.1-pro"
```
**After:**
```python
llm_model: str = "gemini-2.5-flash"   # 2026-05-03: gemini-3.x returns 404 on free tier
```

---

### 3. `pinterest_automation/session_pool.py` — partition by handle

**Line 44-58** (`SessionPool.__init__` + `_get_session_dir`):

Today the pool is one flat `Dict[str, SessionInfo]` keyed by an internal `pool_N` id, all using `BrowserConfig.session_name` as the profile dir prefix.

After the refactor:
- `SessionPool` keeps a separate dict-per-handle: `self._sessions: Dict[str, Dict[str, SessionInfo]]` (handle → session_id → info).
- `acquire(handle: str | None = None)` resolves `handle` via `AccountRegistry`, looks up that handle's sub-dict.
- `_get_session_dir(handle, session_id)` returns `account.session_dir / f"pool_{session_id}"` — one Firefox profile path per (handle, session_id) tuple.
- `_create_session(handle)` calls `kill_firefox_locks_for(account.session_dir)` (see step 4) — surgical, not global.
- `release(session, healthy=True)` already takes a `SessionInfo`; the info now also carries `handle` so the pool knows where to put it back.

Estimated diff: ~50 lines changed in `session_pool.py`.

---

### 4. `pinterest_automation/browser_utils.py` — surgical Firefox kill

**The blocker.** Today `kill_firefox_locks` runs `taskkill /F /IM firefox.exe` which kills every Firefox on the machine. Two pipelines = each one nukes the other's browser.

**Replace** the global taskkill with a PID-targeted kill driven by Playwright's own process tracking. Public API gains a second function:

```python
# UNCHANGED - still used at supervisor startup before any session exists
def kill_firefox_locks(session_dir: Path) -> list[str]: ...

# NEW - used between Playwright launches
def kill_firefox_locks_for(session_dir: Path, *, pid_hint: int | None = None) -> list[str]:
    """
    Removes lock files in the given profile dir. If pid_hint is supplied,
    only that PID is killed (via taskkill /F /PID <pid>). If pid_hint is None,
    walks `wmic process where "CommandLine like '%--profile <dir>%'" get ProcessId`
    to find Firefox(es) bound to THIS profile only and kills only those.
    Never touches Firefox processes bound to other profiles.
    """
```

The blanket `kill_firefox_locks` stays for the existing startup-cleanup path (single-account usage) but is no longer called between session creates.

`session_pool.py:_create_session` switches to `kill_firefox_locks_for(account.session_dir)`.

`rankstein_mcp_server.py:2031` (the duplicated copy of this function) gets deleted; the MCP path imports from `browser_utils` instead — closes a long-standing drift hazard noted in `STATUS.md`.

Estimated diff: +60 lines in `browser_utils.py`, -67 lines in `rankstein_mcp_server.py` (delete the dupe), 4 import-line edits.

---

### 5. `pinterest_automation/rate_limiter.py` — per-account budget

**Line 17-153.** Today the limiter has flat dicts: `_daily_counts[operation]`, `_hourly_counts[operation]`. Two accounts hammering Pinterest under the same `operation="pin_post"` would share a budget — the limiter would let account A burn account B's budget.

**After:** all dicts gain a handle dimension.

```python
self._daily_counts: Dict[tuple[str, str], int] = {}   # (handle, op) -> count
self._hourly_counts: Dict[tuple[str, str], int] = {}
self._failure_streaks: Dict[tuple[str, str], int] = {}
self._cooldown_until: Dict[tuple[str, str], float] = {}
```

Method signatures gain `handle: str`:
```python
def can_execute(self, operation: str = "pin_post", handle: str = None) -> bool
def record_execution(self, operation: str = "pin_post", handle: str = None) -> None
def get_delay(self, operation: str = "pin_post", handle: str = None) -> float
def wait(self, operation: str = "pin_post", handle: str = None) -> None
```

`handle=None` resolves to `AccountRegistry.default.handle` so existing callers pinning the default account need zero changes.

Per-account caps come from the account roster (`max_pins_per_day`), overriding the global `RateLimitConfig.daily_pin_limit` per handle. This is the only field where account-level config genuinely matters.

Estimated diff: ~80 lines in `rate_limiter.py`.

---

### 6. `pinterest_automation/job_queue.py` — `account_handle` column

The SQLite schema needs one new column. Migration is forward-only:

```sql
ALTER TABLE jobs ADD COLUMN account_handle TEXT NOT NULL DEFAULT 'rida';
CREATE INDEX IF NOT EXISTS idx_jobs_handle_status ON jobs(account_handle, status);
```

`enqueue_pin_upload(...)` gains `account_handle: str = None` (resolves to default) and writes it.

`fetch_next(handle: str)` filters: `SELECT ... WHERE status='pending' AND account_handle = ? ORDER BY priority, created_at LIMIT 1`.

The supervisor (next step) calls `fetch_next(my_handle)` so each supervisor only sees its own queue lane.

Estimated diff: ~30 lines in `job_queue.py`, +1 migration in the existing `_init_schema` method.

---

### 7. `pinterest_automation/supervisor.py` — one supervisor per account

Today `AutonomousSupervisor` is a single class managing one event loop. Multi-account turns it into per-handle workers spawned by an outer orchestrator.

```python
class AutonomousSupervisor:
    def __init__(self, account: PinterestAccount): ...
    async def run(self) -> None: ...    # unchanged shape

class SupervisorFleet:
    """Spawns one AutonomousSupervisor per account, supervises them."""
    def __init__(self, registry: AccountRegistry = None): ...
    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            for account in self.registry.all():
                tg.create_task(AutonomousSupervisor(account).run())
```

`run_autonomous.py:run_supervisor` switches to `SupervisorFleet().run()`.

Single-account behavior: the registry returns one account, fleet spawns one supervisor — identical to today's runtime.

Estimated diff: ~40 lines in `supervisor.py`, ~10 in `run_autonomous.py`.

---

### 8. `rankstein_mcp_server.py` — accept `account_handle` arg

Three MCP tools need a new optional `account_handle: str = ""` parameter:

| Tool | Today | After |
|---|---|---|
| `upload_pin_to_pinterest` (line 877+) | `session_dir = PROJECT_ROOT / "data" / "sessions" / "pinterest_rida_v7"` | `account = get_registry().get(account_handle or None); session_dir = account.session_dir; email/password from account` |
| `check_pinterest_session` (line 1977+) | `session_dirs = {"uploader": ..., "harvester": ..., "remasterer": ...}` keyed by **role** | Keep role mapping but layer account on top: `session_dir = account.session_dir / f"role_{role}"` (the role partitioning was for parallel role workers on one account; account is orthogonal) |
| `pinterest_relogin` (line 2243+) | reads `PINTEREST_EMAIL`/`PINTEREST_PASSWORD` env vars directly | resolves `account_handle` → reads the account's email/password fields |

For backward compat: `account_handle=""` resolves to default, so existing Gemini agent prompts that don't pass the arg keep working.

Estimated diff: ~60 lines across 3 tools.

---

### 9. `gemini_rankstein_prompt.md` — workflow guidance

Phase 5.5 currently calls `upload_pin_to_pinterest(...)` with no account context. After:

```diff
- 21. Call `upload_pin_to_pinterest(pin_path, title, description_es, "https://recetadolce.com/{slug}")`.
+ 21. Call `upload_pin_to_pinterest(pin_path, title, description_es, "https://recetadolce.com/{slug}", account_handle=<handle>)`
+     where `<handle>` matches the niche of the recipe (postres → "alt1" if configured, else default).
+     Omit account_handle to use the default (`rida`) account.
```

Plus a new "Account selection" sub-section explaining how the agent picks a handle from a recipe's category.

---

### 10. `.env.example` — document new vars (no edit to `.env` itself)

```bash
# Default account (legacy names, still primary)
PINTEREST_EMAIL=...
PINTEREST_PASSWORD=...

# Additional accounts (one pair per handle, names match data/accounts.json)
PINTEREST_EMAIL_ALT1=...
PINTEREST_PASSWORD_ALT1=...
```

---

## Migration strategy

1. **Phase A — refactor with one account.** Land all the file changes above. `data/accounts.json` ships with one account synthesised from the legacy env vars. End-state: same behavior as today, but every code path now goes through `AccountRegistry`. Risk: low. Tests: existing pytest suite must pass; one new test confirms `get_registry().default.handle == "rida"` when no roster file exists.

2. **Phase B — add second account.** User creates a second Pinterest account, populates `PINTEREST_EMAIL_ALT1`/`PINTEREST_PASSWORD_ALT1`, adds an entry to `data/accounts.json`. First run: `gemini` calls `pinterest_relogin(account_handle="alt1")` to seed the session dir. Verify with `check_pinterest_session(account_handle="alt1")`.

3. **Phase C — fleet runs.** `python run_autonomous.py run` spawns N supervisors, one per account. Validation: simultaneously enqueue 2 pins (one per account), watch `data/logs/automation.log` show both processes uploading concurrently to different `data/sessions/<handle>/` profiles, with PID-targeted Firefox kills not interfering.

4. **Phase D — niche-aware routing.** Update `automation_enqueue_pin` (and the agent prompt) so a recipe in category "postres" routes to a postres-specialised account if one exists. Falls through to default if not.

Each phase is independently shippable — Phase A can land without B/C/D ever happening if the user decides one account is enough.

---

## Concurrency & rate-limiting considerations

- **Pinterest abuse heuristics are PER-ACCOUNT, not per-IP** for normal usage. Two accounts on the same residential IP doing organic-looking pin pacing is fine; it's behavioral patterns (rapid-fire posting, identical pin metadata across accounts, headless-detected fingerprints) that get flagged. The existing rate limiter's 12-17s base delay + jitter already addresses pacing; per-account budgets prevent one account from overflowing into another's quota.
- **One Firefox process per account at a time.** Don't try to run two supervisors against the same handle in parallel — `account.session_dir` is single-writer. The fleet enforces this trivially (one supervisor per handle).
- **CPU/RAM ceiling.** Each Firefox profile is ~250 MB resident. 4 accounts in parallel = ~1 GB browser footprint plus Playwright + Python overhead. Acceptable on the user's box (154 GB free disk, RAM not measured but presumably ample).
- **Same-IP fingerprinting risk.** Mitigated by giving each account its own `BrowserConfig.user_agent` override in the roster (optional field added in Phase B). For now all accounts share the UA — fine for low-volume validation.

---

## Verification plan

End-to-end smoke after Phase A:
1. `python -m pytest tests/ -q` — all green, including a new `tests/unit/test_account_registry.py` that:
   - Loads the synthesized single-account roster when `accounts.json` is absent.
   - Loads a 2-account roster from a temp `accounts.json`.
   - Routes by niche (account A handles postres, B handles default).
2. `python rankstein_mcp_server.py` — boots; `check_pinterest_session(account_handle="rida")` returns `likely_valid=true` (existing session reused).
3. `gemini -p "Run health_check then list_keywords" --model gemini-2.5-flash --yolo` — the MCP tool calls succeed, no behavioral change.

End-to-end smoke after Phase C (multi-account):
1. Create real second Pinterest account, add to roster.
2. `python run_autonomous.py enqueue-pin <hero1.jpg> "Title A" "Desc A" --account-handle rida`
3. `python run_autonomous.py enqueue-pin <hero2.jpg> "Title B" "Desc B" --account-handle alt1`
4. `python run_autonomous.py run` — fleet starts both supervisors. Watch `data/logs/automation.log` for two distinct `[supervisor-rida]` and `[supervisor-alt1]` log streams uploading concurrently. Confirm `data/sessions/pinterest_rida_v7/cookies.sqlite` and `data/sessions/pinterest_alt1/cookies.sqlite` are both modified mtime-fresh.

---

## Critical files (touch list)

- `pinterest_automation/account.py` — **new**
- `pinterest_automation/config.py` — small edits (3 locations)
- `pinterest_automation/session_pool.py` — partition by handle
- `pinterest_automation/browser_utils.py` — add `kill_firefox_locks_for`
- `pinterest_automation/rate_limiter.py` — per-handle dimension on all dicts
- `pinterest_automation/job_queue.py` — `account_handle` column + dispatch filter
- `pinterest_automation/supervisor.py` — `SupervisorFleet` wrapper
- `rankstein_mcp_server.py` — 3 tool signatures gain `account_handle`; delete duplicated `_kill_firefox_locks` (line 2031)
- `run_autonomous.py` — fleet entry point; `--account-handle` CLI arg on `enqueue-pin`
- `gemini_rankstein_prompt.md` — Phase 5.5 account selection guidance
- `.env.example` — document `PINTEREST_EMAIL_<HANDLE>` pattern
- `data/accounts.json` — **new** (Phase B optional, A synthesises if absent)
- `tests/unit/test_account_registry.py` — **new**
- `tests/unit/test_rate_limiter_per_handle.py` — **new**

Total estimated effort: **~1.5-2 days of focused work**, ~600 LOC net add, ~70 LOC net delete (the duplicate Firefox helper goes away). Reversible — Phase A is a no-op behavior change, Phase B+ are additive config.

---

## Decisions (locked 2026-05-03)

1. **Account creation is manual.** User signs each new Pinterest account up via the Pinterest UI; no programmatic signup. The refactor only handles login (via `pinterest_relogin(account_handle=...)`) and session persistence afterward.
2. **Niche routing = hub-and-spoke.** The default account (`rida`) keeps posting everything (every recipe category routes to it). Specialised accounts opt-in to a subset of niches and *additionally* receive matching pins. Concretely: a recipe in category `postres` enqueues two pins — one to `rida`, one to any specialised account whose `niches` includes `postres`. This minimises blast radius (if a specialised account is suspended, the default account still gets the pin) and makes single-account → multi-account migration purely additive. Implementation: `enqueue_pin_upload` resolves to a *list* of accounts, not one; the JobQueue inserts one row per matched account.
3. **Different user-agent per account.** `PinterestAccount` gains an optional `user_agent: str` field. If absent, falls back to `BrowserConfig.user_agent`. Roster ships with the default UA on `rida` (matches today's behavior) and a slightly varied UA on each new account to reduce shared-fingerprint risk. Roster format gets one new field:
   ```json
   { "handle": "alt1", "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0", ... }
   ```
4. **Warmup ramp = out of scope for this PR**, flagged for a follow-up. The roster's `max_pins_per_day` is the enforcement knob today; user manually steps it from 5 → 25 → 100 → 300 over a new account's first 30 days. A future PR can automate the ramp via an `account_age_days` calculation against an `onboarded_at` timestamp on each roster entry — but that's a separate concern from the partitioning refactor.

---

## Status

Plan locked. Ready to execute Phase A on approval.

Phase A scope (the only phase that touches code in this PR):
- New: `pinterest_automation/account.py`, `data/accounts.json` synthesiser, `tests/unit/test_account_registry.py`, `tests/unit/test_rate_limiter_per_handle.py`
- Edited: `pinterest_automation/{config,session_pool,browser_utils,rate_limiter,job_queue,supervisor}.py`, `rankstein_mcp_server.py`, `run_autonomous.py`, `gemini_rankstein_prompt.md`, `.env.example`
- Behavior: identical to today (single account, single supervisor) — every existing call path resolves to default account when no handle is passed. Tests prove it.

Phases B/C/D (config-only / per-account ops, no PR needed unless niche routing requires logic changes).
