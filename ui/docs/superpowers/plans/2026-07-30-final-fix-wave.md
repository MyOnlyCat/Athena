# Athena-Node Final Review Fix Wave Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every Critical and Important item in the final review while preserving the terminal, file-transfer, deployment, and master-runtime contracts.

**Architecture:** Put SSH host-key verification in one AsyncSSH connection boundary shared by terminal, files, deployment, and connection testing. Keep navigation requests, upload-batch completion, master persistence, and runtime activation as explicitly owned state machines so cancellation or stale async work cannot split their observable state.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/aiosqlite, AsyncSSH 2.23.1, Pytest, React 19, TypeScript, Axios, Vitest, Nginx, Docker Compose.

## Global Constraints

- Every behavior change follows focused RED, minimal GREEN, then focused regression verification.
- SSH pin validation uses a truthy empty `known_hosts` source plus `SSHClient.validate_host_public_key`; `known_hosts=None` is forbidden because AsyncSSH 2.23.1 disables the callback in that mode.
- Password authentication may begin only after the AsyncSSH key-exchange host-key callback accepts the saved SHA-256 fingerprint.
- Upload/download Axios calls use `timeout: 0`; their existing AbortSignal cancellation remains intact.
- Preserve the request-generation behavior for user navigation and the batch/concurrency behavior of the upload queue.
- A successful master-settings database commit and candidate activation are one cancellation-resilient owned operation.
- Runtime status is exactly `unconfigured`, `connecting`, `online`, `error`, or `stopped`.
- Do not stage preview logs, quick-dev files, start-dev files, databases, virtual environments, node_modules, secrets, or unrelated files.

---

### Task 1: Shared pinned SSH boundary

**Files:**
- Modify: `api/app/services/ssh.py`
- Modify: `api/app/services/hosts.py`
- Modify: `api/app/services/files.py`
- Modify: `api/app/services/terminal.py`
- Modify: `api/app/services/deployment_gateway.py`
- Modify: `api/app/services/executor.py`
- Modify: `api/app/api/v1/files.py`
- Modify: `api/app/api/v1/terminal.py`
- Test: `api/tests/test_hosts.py`
- Test: `api/tests/test_files.py`
- Test: `api/tests/test_terminal.py`
- Test: `api/tests/test_deployments.py`

**Interfaces:**
- `HostConnection(..., host_key_fingerprint: str | None = None)` carries the saved pin.
- `connect_ssh(connection, *, allow_tofu=False, connect_timeout=None)` is the only AsyncSSH connect boundary.
- `PinnedSSHClient.validate_host_public_key(...)` compares `key.get_fingerprint("sha256")` with the saved pin.

- [ ] Add focused tests which fail because terminal, files, deployment, and saved-host connection testing currently omit or post-check the pin.
- [ ] Run the four focused API test modules and record the expected changed-key/resource-boundary failures.
- [ ] Implement the shared validator with a truthy empty known-hosts payload and `client_factory`; translate a rejected saved pin to a stable host-key-changed exception.
- [ ] Pass the saved fingerprint from terminal/file routes and the deployment executor; keep TOFU only in explicit connection testing.
- [ ] Clear a host fingerprint only when address or port changes; preserve it for name, username, password, tag, or locality edits.
- [ ] Re-run the focused tests and static checks.

### Task 2: SSH acquisition cleanup and terminal error states

**Files:**
- Modify: `api/app/services/files.py`
- Modify: `api/app/services/terminal.py`
- Modify: `api/app/api/v1/terminal.py`
- Modify: `ui/src/features/terminal/useTerminalSession.ts`
- Modify: `ui/src/features/terminal/TerminalPane.tsx`
- Test: `api/tests/test_files.py`
- Test: `api/tests/test_terminal.py`
- Test: `ui/tests/terminal.test.tsx`

**Interfaces:**
- Failed SFTP/process creation closes and awaits the already-open SSH connection.
- `AsyncTerminal.close()` attempts stdin EOF, connection close, and `wait_closed()` independently.
- WebSocket error codes map to Chinese UI states for authentication, changed host key, network, channel, and generic open failures.

- [ ] Add cleanup tests for failed `start_sftp_client()`, failed `create_process()`, each independent terminal-close step, early download `aclose()`, and remote-read failure.
- [ ] Add WebSocket/API error-mapping tests and UI label tests for connecting, connected, normal close, auth, host-key, network, channel, and open failure.
- [ ] Run focused API/UI tests and verify RED.
- [ ] Implement best-effort resource cleanup, stable error classification, and UI state/label mapping.
- [ ] Re-run focused tests, typecheck, Ruff, and mypy.

### Task 3: Streaming transfer duration and proxying

**Files:**
- Modify: `ui/src/shared/api/client.ts`
- Modify: `deploy/nginx.conf`
- Test: `ui/tests/files.test.tsx`
- Test: `api/tests/test_deployment_config.py`

**Interfaces:**
- `filesApi.upload()` and `filesApi.download()` send Axios `timeout: 0`.
- `/api/v1/files/` disables `proxy_request_buffering` and `proxy_buffering` while retaining proxy headers and the global 1024 MiB limit.

- [ ] Add Axios option tests and an Nginx file-location contract test; verify both fail.
- [ ] Add `timeout: 0` to both transfers and a specific non-buffered files location in Nginx.
- [ ] Re-run focused tests and later validate the composed deployment configuration.

### Task 4: Upload/navigation race removal and path validation

**Files:**
- Modify: `ui/src/features/terminal/useUploadQueue.ts`
- Modify: `ui/src/features/terminal/FileManager.tsx`
- Test: `ui/tests/upload-queue.test.tsx`
- Test: `ui/tests/files.test.tsx`

**Interfaces:**
- Each `enqueue()` batch emits at most one completion refresh after all of that batch's tasks settle and at least one succeeds.
- User navigation owns its request generation; upload refresh requests are deferred and coalesced until the latest navigation settles.
- Non-absolute path drafts show `远程路径必须是绝对路径` without calling the API.

- [ ] Add controlled-promise tests for upload completion during pending navigation, one refresh for a multi-file batch, and client-side rejection of a relative path.
- [ ] Run the two focused Vitest files and verify RED.
- [ ] Add batch IDs/notification tracking to the queue and split navigation from coalesced refresh ownership in `FileManager`.
- [ ] Re-run focused tests, UI typecheck, and ESLint.

### Task 5: Cancellation-resilient master commit/activation

**Files:**
- Modify: `api/app/api/v1/master_settings.py`
- Test: `api/tests/test_master_settings.py`

**Interfaces:**
- The owned operation performs `session.commit()` and then `runtime.activate(candidate)` before propagating caller cancellation.
- Commit failure rolls back and discards the candidate without replacing the old runtime.

- [ ] Add a real temporary-SQLite/aiosqlite regression test which gates a queued real SQLite commit, cancels the route task, releases the commit, and asserts database host/token and active runtime host/token are identical.
- [ ] Run only that test and verify the old route leaves database/runtime split.
- [ ] Implement one shielded owned commit-and-activate helper, preserving failure cleanup.
- [ ] Re-run the focused cancellation, commit-failure, concurrent-update, and runtime cleanup tests.

### Task 6: Real master connectivity status

**Files:**
- Modify: `api/app/services/inventory_sync.py`
- Modify: `api/app/services/master_runtime.py`
- Modify: `api/app/schemas/master_setting.py`
- Modify: `ui/src/shared/api/types.ts`
- Modify: `ui/src/features/settings/MasterSettingsPage.tsx`
- Test: `api/tests/test_inventory_sync.py`
- Test: `api/tests/test_master_settings.py`
- Test: `ui/tests/master-settings.test.tsx`

**Interfaces:**
- `InventorySynchronizer.status` begins `connecting`, becomes `online` after a successful heartbeat/poll cycle, and becomes `error` after either boundary fails.
- `MasterRuntime.status` returns the stable enum, including `unconfigured` for an activated empty configuration and `stopped` after shutdown.
- The settings page maps all five statuses to Chinese labels.

- [ ] Add heartbeat/poll success and failure tests, runtime unconfigured/connecting/stopped tests, response-enum assertions, and Chinese UI label tests.
- [ ] Run focused API/UI tests and verify RED.
- [ ] Track status in the synchronizer, retain an unconfigured active slot, expose a typed literal enum, and render the label map.
- [ ] Re-run focused tests and static checks.

### Task 7: Full verification, report, and exact commits

**Files:**
- Update if contract text changed: `docs/api/openapi.json`, affected Markdown docs.
- Create: `ui/.superpowers/sdd/2026-07-30-terminal-master-settings-transfers/final-fix-report.md`

- [ ] Run full API Pytest, Ruff, mypy, and a fresh Alembic upgrade against a temporary SQLite database.
- [ ] Run full UI Vitest, typecheck, ESLint, and production build.
- [ ] Run `docker compose --env-file .env.example config`.
- [ ] Re-read the brief line by line, inspect the complete diff, and confirm forbidden/unrelated files are unstaged.
- [ ] Write the final report with RED/GREEN evidence, full command results, changed contracts, AsyncSSH source finding, and residual concerns.
- [ ] Stage exact paths, create one or a small number of logical commits, then verify commit contents and a clean scoped diff.
