# Terminal, Master Settings, and Transfers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair interactive Web SSH and remote downloads, add application fullscreen, editable paths, cancellable batch uploads, and runtime-editable master-node settings.

**Architecture:** Keep terminal and file payloads streaming end to end. Add a page-scoped upload queue in React, a SQLite-backed encrypted master setting, and one runtime manager which owns the replaceable master client and worker loop.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, AsyncSSH, Pytest, React 19, TypeScript, Ant Design, Axios, Vitest.

## Global Constraints

- Web SSH input and output remain binary because AsyncSSH is opened with `encoding=None`.
- Master-node Token is encrypted at rest and never returned in plaintext.
- Database master settings override environment defaults after the first saved configuration.
- Batch upload accepts multiple files only, runs at most 3 transfers concurrently, and is cancelled when the terminal page unmounts or the active host changes.
- Terminal fullscreen is application fullscreen, not the browser Fullscreen API.
- Preserve unrelated dirty working-tree files and stage each commit by exact path.

---

### Task 1: Repair the binary Web SSH bridge

**Files:**
- Modify: `api/app/services/terminal.py`
- Modify: `api/app/api/v1/terminal.py`
- Test: `api/tests/test_terminal.py`

**Interfaces:**
- Consumes: `bridge_terminal(websocket, terminal)`.
- Produces: `AsyncTerminal.write(data: bytes) -> None` which writes bytes to the binary AsyncSSH stdin; structured WebSocket error frames for bridge failures.

- [ ] **Step 1: Write the failing terminal tests**

Add fake binary process, terminal, and WebSocket classes. Assert that an input frame containing Base64 for `b"ls\r"` reaches `process.stdin.write` as `bytes`, and that a bridge exception closes the terminal and emits `{"type": "error", "code": "TERMINAL_BRIDGE_ERROR"}` when the socket is still available.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `api\.venv\Scripts\python -m pytest api/tests/test_terminal.py -q`

Expected: FAIL because `AsyncTerminal.write()` decodes bytes to `str` and bridge failures are not translated to an error frame.

- [ ] **Step 3: Implement the minimal binary-safe bridge**

Change `AsyncTerminal.write()` to pass `bytes` directly. In `bridge_terminal()`, cancel and await the peer task, send the structured error for non-disconnect exceptions, and always close the terminal exactly once.

- [ ] **Step 4: Verify GREEN and static checks**

Run:

```powershell
api\.venv\Scripts\python -m pytest api/tests/test_terminal.py -q
api\.venv\Scripts\python -m ruff check api/app/services/terminal.py api/app/api/v1/terminal.py api/tests/test_terminal.py
api\.venv\Scripts\python -m mypy api/app
```

Expected: all pass.

- [ ] **Step 5: Commit**

Commit exact Task 1 paths with message `fix(api): keep web ssh bridge binary safe`.

### Task 2: Make downloads reliable and paths editable

**Files:**
- Modify: `api/app/api/v1/files.py`
- Modify: `api/app/services/files.py`
- Modify: `api/tests/test_files.py`
- Modify: `ui/src/shared/api/client.ts`
- Modify: `ui/src/features/terminal/FileManager.tsx`
- Modify: `ui/tests/files.test.tsx`

**Interfaces:**
- Produces: RFC 5987-compatible `Content-Disposition`; `filesApi.download(hostId, path)` returning `{ blob, filename }`; path input which commits only after a successful list response.

- [ ] **Step 1: Write failing API download tests**

Add tests for a UTF-8 filename, complete content, and generator cleanup after streaming. Assert `filename*=UTF-8''...` appears without exposing unsafe quotes or line breaks.

- [ ] **Step 2: Verify API RED**

Run: `api\.venv\Scripts\python -m pytest api/tests/test_files.py -q`

Expected: FAIL because the current header only emits an ASCII `filename`.

- [ ] **Step 3: Implement the safe streaming filename**

Build `Content-Disposition` using a sanitized ASCII fallback plus `urllib.parse.quote(filename)` for `filename*`. Preserve the async generator `finally` cleanup.

- [ ] **Step 4: Write failing UI path and download tests**

Assert that Enter on `/var/log` calls `filesApi.list(hostId, "/var/log")`, a rejected request leaves `/` rendered, and clicking download uses the response filename and reports failures.

- [ ] **Step 5: Verify UI RED**

Run: `npm test -- --run tests/files.test.tsx`

Expected: FAIL because the path is a button and `download()` returns a raw Axios response.

- [ ] **Step 6: Implement editable paths and delayed URL cleanup**

Keep `pathDraft` separate from the committed `path`; update both only after successful listing. Make `filesApi.download()` parse `Content-Disposition`, return a Blob and filename, append/click/remove the anchor, and revoke its URL on a zero-delay callback.

- [ ] **Step 7: Verify GREEN**

Run focused API/UI tests, UI typecheck, and ESLint for changed files. Expected: all pass.

- [ ] **Step 8: Commit**

Commit exact Task 2 paths with message `fix(files): support reliable downloads and path navigation`.

### Task 3: Add the cancellable batch upload queue

**Files:**
- Create: `ui/src/features/terminal/useUploadQueue.ts`
- Create: `ui/src/features/terminal/UploadTasks.tsx`
- Modify: `ui/src/features/terminal/FileManager.tsx`
- Modify: `ui/src/features/terminal/TerminalPage.tsx`
- Modify: `ui/src/shared/api/client.ts`
- Modify: `ui/src/shared/api/types.ts`
- Create: `ui/tests/upload-queue.test.tsx`

**Interfaces:**
- Produces: `useUploadQueue(hostId, onCompleted)` with `enqueue(files, directory)`, `cancel(id)`, `cancelAll()`, `tasks`, and `summary`.
- Consumes: `filesApi.upload(hostId, path, file, { signal, onProgress })`.

- [ ] **Step 1: Write failing queue tests**

Test that five selected files create five tasks, only three upload promises start before one settles, progress updates the matching task, failure does not block remaining files, and unmount or host change aborts all active requests and marks remaining tasks cancelled.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run tests/upload-queue.test.tsx`

Expected: FAIL because the upload queue hook and task component do not exist.

- [ ] **Step 3: Implement the minimal queue**

Represent tasks with immutable IDs, file, destination, loaded/total bytes, status, and error. Schedule at most three active Axios requests. Give every running task an `AbortController`; cleanup aborts active tasks and prevents queued tasks from starting.

- [ ] **Step 4: Connect the queue to the file panel**

Enable `multiple` on the input, enqueue all selected files against the committed directory, render overall and per-file progress, add cancel-one/cancel-all controls, clear the input value after selection, and refresh the directory after successful transfers settle.

- [ ] **Step 5: Verify GREEN**

Run the upload queue and file tests, then UI typecheck and ESLint. Expected: all pass without state-update-after-unmount warnings.

- [ ] **Step 6: Commit**

Commit exact Task 3 paths with message `feat(ui): add cancellable batch upload queue`.

### Task 4: Add default application fullscreen for Web SSH

**Files:**
- Modify: `ui/src/app/AppShell.tsx`
- Modify: `ui/src/features/terminal/TerminalPage.tsx`
- Modify: `ui/src/features/terminal/TerminalPane.tsx`
- Modify: `ui/src/styles/global.css`
- Create: `ui/tests/terminal-fullscreen.test.tsx`

**Interfaces:**
- Produces: terminal layout state with default `true`, exposed through an outlet context or route-aware shell callback; toolbar buttons with accessible names `退出全屏` and `进入全屏`.

- [ ] **Step 1: Write the failing shell behavior test**

Render the authenticated router at `/terminal`. Assert the sidebar and header are hidden by default, click `退出全屏`, assert both return, then click `进入全屏` and assert they hide again.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run tests/terminal-fullscreen.test.tsx`

Expected: FAIL because `AppShell` always renders its navigation chrome.

- [ ] **Step 3: Implement route-scoped application fullscreen**

Keep fullscreen state in the shell, reset it to true whenever `/terminal` is entered, add a layout class which removes sidebar/header/margins/padding, and pass toggle state to the terminal toolbar without using `document.fullscreenElement`.

- [ ] **Step 4: Verify GREEN**

Run terminal tests, UI typecheck, ESLint, and production build. Expected: all pass.

- [ ] **Step 5: Commit**

Commit exact Task 4 paths with message `feat(ui): open web ssh in application fullscreen`.

### Task 5: Persist and hot-swap master-node configuration

**Files:**
- Create: `api/app/models/master_setting.py`
- Create: `api/app/schemas/master_setting.py`
- Create: `api/app/services/master_settings.py`
- Create: `api/app/services/master_runtime.py`
- Create: `api/app/api/v1/master_settings.py`
- Create: `api/alembic/versions/0005_master_settings.py`
- Modify: `api/app/models/__init__.py`
- Modify: `api/app/main.py`
- Modify: `api/app/services/master_client.py`
- Create: `api/tests/test_master_settings.py`

**Interfaces:**
- Produces: `MasterRuntime.apply(config)`, `MasterRuntime.stop()`, and authenticated GET/POST-test/PUT routes under `/api/v1/master-settings`.
- Persists: singleton row `master_settings(id=1, scheme, host, port, encrypted_token, updated_at)`.

- [ ] **Step 1: Write failing persistence and redaction tests**

Assert GET falls back to environment defaults and returns `has_token` without Token; PUT encrypts a supplied Token; a later PUT with an empty Token retains the ciphertext; invalid host/port returns 422.

- [ ] **Step 2: Verify RED**

Run: `api\.venv\Scripts\python -m pytest api/tests/test_master_settings.py -q`

Expected: FAIL because the routes and model do not exist.

- [ ] **Step 3: Implement model, migration, schemas, and encrypted service**

Use the existing `CredentialCipher`. Normalize scheme/host/port into a base URL and never serialize `encrypted_token`.

- [ ] **Step 4: Write failing runtime replacement tests**

Inject fake clients/workers. Assert test failure leaves the old runtime and database row unchanged; success stops and closes the old runtime before starting exactly one new loop.

- [ ] **Step 5: Implement `MasterRuntime` and integrate lifespan**

Move ownership of `MasterClient`, inventory synchronizer loop, and executor polling from ad hoc lifespan locals into the manager. Serialize `apply()` with an async lock. Start from the database row, else environment defaults; stop cleanly during lifespan shutdown.

- [ ] **Step 6: Implement routes and signed connection test**

GET returns redacted configuration and runtime status. POST `/test` uses the submitted Token or decrypted saved Token. PUT performs validate → signed test → persist → apply, preserving the old runtime and row if testing fails.

- [ ] **Step 7: Verify GREEN and migration**

Run master settings tests, full API tests, Ruff, mypy, and `alembic upgrade head` against a temporary SQLite URL. Expected: all pass.

- [ ] **Step 8: Commit**

Commit exact Task 5 paths with message `feat(api): add runtime master node settings`.

### Task 6: Add the master-node configuration UI

**Files:**
- Create: `ui/src/features/settings/MasterSettingsPage.tsx`
- Create: `ui/tests/master-settings.test.tsx`
- Modify: `ui/src/app/AppRouter.tsx`
- Modify: `ui/src/app/AppShell.tsx`
- Modify: `ui/src/shared/api/client.ts`
- Modify: `ui/src/shared/api/types.ts`
- Modify: `ui/src/styles/global.css`

**Interfaces:**
- Produces: `/master-settings` page and navigation item; `masterSettingsApi.get/test/update`.

- [ ] **Step 1: Write failing page tests**

Assert the form loads scheme/host/port and a blank Token field, displays `has_token` as “已保存”, submits an empty Token without replacing it, tests connectivity, and renders API errors.

- [ ] **Step 2: Verify RED**

Run: `npm test -- --run tests/master-settings.test.tsx`

Expected: FAIL because the API client, page, route, and menu entry do not exist.

- [ ] **Step 3: Implement the page and navigation**

Add protocol select, host, numeric port, password Token input, status badge, test button, and save/apply button. Do not put a saved Token into component state or DOM.

- [ ] **Step 4: Verify GREEN**

Run the focused test, full UI tests, typecheck, ESLint, and production build. Expected: all pass.

- [ ] **Step 5: Commit**

Commit exact Task 6 paths with message `feat(ui): add master node configuration`.

### Task 7: Complete documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `TASKS.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/api/local-api.md`
- Modify: `docs/api/master-node-protocol.md`
- Modify: `docs/api/websocket-protocol.md`
- Create: `docs/file-transfers.md`
- Regenerate: `docs/api/openapi.json`

**Interfaces:**
- Documents the exact shipped routes, configuration precedence, application fullscreen, binary terminal behavior, path navigation, upload concurrency, cancellation, and download behavior.

- [ ] **Step 1: Update documents and OpenAPI**

Describe database-over-environment precedence, Token redaction, live client replacement, upload task lifecycle, the three-file concurrency limit, leave-page cancellation, and troubleshooting for SSH/disconnected states.

- [ ] **Step 2: Run the complete verification suite**

Run:

```powershell
api\.venv\Scripts\python -m pytest api/tests -q
api\.venv\Scripts\python -m ruff check api
api\.venv\Scripts\python -m mypy api/app
npm test -- --run
npm run typecheck
npm run lint
npm run build
docker compose config
```

Expected: every command succeeds. If Docker Engine is available, additionally run `docker compose build`; otherwise record the environmental limitation without claiming a successful image build.

- [ ] **Step 3: Perform local smoke verification**

Start API and UI on their development ports, verify `/api/v1/health`, authenticated `GET /api/v1/master-settings`, UI login, `/terminal`, and `/master-settings`, then stop only the processes listening on those ports.

- [ ] **Step 4: Review the final diff**

Confirm no Token, password, data file, log, virtual environment, `node_modules`, generated TypeScript artifact, or unrelated dirty file is staged.

- [ ] **Step 5: Commit**

Commit documentation and generated OpenAPI with message `docs: complete terminal and master settings guide`.

- [ ] **Step 6: Final delivery**

Report commits, verification commands and results, any Docker Engine limitation, and the principal changed files.

