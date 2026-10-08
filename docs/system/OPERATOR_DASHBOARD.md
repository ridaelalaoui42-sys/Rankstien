# RankStein Operator

RankStein owns its local control plane at `http://127.0.0.1:7000/operator`.
It does not require the Odysseus app, its database, its authentication module,
or a Next.js server. The `frontend/` directory remains a recipe-site template
for the site factory and is no longer started by the suite.

## Startup

Use `python rankstein.py suite start` or `start_all_services.ps1` for the full
service suite. The existing RankStein logon and daily tasks use this controller.
For the operator alone:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.operator:app --host 127.0.0.1 --port 7000 --no-proxy-headers
```

Disable the legacy `Odysseus_Server` scheduled task before migrating port 7000.
An occupied or unhealthy service port fails closed: startup reports a conflict
without killing its holder. Stop a verified legacy process explicitly, never
kill arbitrary Node/Python processes or a process selected only by its port.

## Runtime Ownership

- API and assets: `backend/operator.py`, `backend/api/operator_routes.py`, and `backend/static/operator/`.
- Evidence-backed workflow snapshots: `backend/services/operator_pipeline.py`.
- Operator-launched process registry: `data/runtime/operator_processes.json`.
- Operator-launched logs: `data/logs/operator/`.
- Existing production state, queues, domain manifests, profiles, and reports remain in place.

Open workflows and completed/failed history are separate. Workflow stages show
the last recorded evidence, not proof that a writer is currently running. Dashboard statistics
are derived from runtime evidence; unavailable telemetry is not a success.
Roadmap `Live` counts describe persisted roadmap state, not a new audit of every
historical article. Recipe pin IDs and browser profile presence are labeled as
recorded evidence, not proof of current platform authentication.

## Controls And Security

The dashboard offers bounded domain-scoped article batches, maintained
audit/seed and trend commands, supervisor controls, board normalization, and
selective transient DLQ recovery. Mutations require explicit confirmation.
The confirmed Stop batch action targets only the tracked production process
and its child article workers. It leaves the Pinterest supervisor and queued
jobs running. A failed stop does not overwrite the process registry, and a
finished process retains its recorded outcome.
Starting services does not start a production batch. Supervisor startup may
publish already-pending queue jobs.

The app binds to loopback only. It rejects remote peers, invalid Host headers,
cross-origin/cross-site requests, and mutations without the per-process operator
session token. Do not expose it through a public reverse proxy. No service role
keys, Pinterest passwords, cookie contents, or session profile paths are sent
to the UI. Scripts and icon assets are served locally.

The overview pin total is a separate all-account snapshot; filtering the pin
feed never replaces it. Automatic global pin-count refreshes are coalesced and
bounded to one request per 30 seconds. Pausing live telemetry is labeled as a
paused/snapshot view.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_operator.py tests/unit/test_operator_pipeline.py tests/unit/test_suite_controller.py -q
```

Browser validation covers all views, desktop/mobile layouts, keyboard-accessible
dialogs, domain filtering, live API loading, console errors, and screenshots.
Verification must not publish content or alter live queues simply to test a UI.
