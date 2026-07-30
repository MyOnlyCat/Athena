# Athena Node Quick Development Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a double-clickable Windows CMD launcher that prepares missing dependencies, starts the API and UI, verifies both services, and opens the UI.

**Architecture:** `ui/start-dev.cmd` is a stable, minimal entry point. It delegates all path resolution, dependency checks, environment injection, service reuse, process startup, and readiness polling to `ui/scripts/start-dev.ps1`.

**Tech Stack:** Windows CMD, Windows PowerShell 5.1+, Node.js/npm, Python 3.12+, Uvicorn, Vite

## Global Constraints

- The user-facing entry point is `ui/start-dev.cmd`.
- Missing `node_modules` and `api/.venv` dependencies are installed automatically.
- Development secrets are passed only to the API child process; no `.env` file is created or overwritten.
- API uses `127.0.0.1:8000`; UI uses `localhost:5173`.
- Healthy existing services are reused; unknown port owners are never terminated.
- No Git commit is created unless the user explicitly requests one.

---

### Task 1: CMD entry point and PowerShell launcher

**Files:**
- Create: `ui/start-dev.cmd`
- Create: `ui/scripts/start-dev.ps1`
- Create: `ui/scripts/test-start-dev.ps1`
- Modify: `api/pyproject.toml`

**Interfaces:**
- Consumes: sibling directories `ui` and `api`, `ui/package.json`, `api/pyproject.toml`
- Produces: `start-dev.cmd`; `start-dev.ps1 -SkipBrowser -StartupTimeoutSeconds <int>`

- [ ] **Step 1: Write the failing launcher behavior test**

Create `test-start-dev.ps1` so it invokes `start-dev.cmd --self-test` from a
different current directory. The command must resolve the sibling UI/API projects,
validate Node/npm/Python prerequisites without starting services, print
`SELF_TEST_OK`, and exit zero.

- [ ] **Step 2: Run the structural test and verify it fails**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-start-dev.ps1
```

Expected: FAIL with `Expected launcher does not exist`.

- [ ] **Step 3: Implement the minimal CMD entry**

`start-dev.cmd` resolves files relative to `%~dp0`, calls PowerShell with
`-ExecutionPolicy Bypass`, propagates the exit code, and pauses only after failure.

- [ ] **Step 4: Implement the PowerShell launcher**

Implement focused functions for command discovery, Python version selection,
dependency preparation, TCP/HTTP checks, readiness polling, and process startup.
Use `try/finally` when changing the current directory or temporarily setting
`ATHENA_*` environment variables. Ensure `api/data` exists before API startup.
Declare setuptools package discovery as `app*` in `api/pyproject.toml` so
`pip install -e ".[dev]"` does not mistake `alembic` for an application package.

- [ ] **Step 5: Run the structural test and syntax parser**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-start-dev.ps1
powershell.exe -NoProfile -Command "$errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path '.\scripts\start-dev.ps1'), [ref]$null, [ref]$errors); if ($errors.Count) { $errors | ForEach-Object Message; exit 1 }"
```

Expected: both commands exit 0.

### Task 2: Real startup and repeat-run verification

**Files:**
- Modify only if verification exposes a defect: `ui/scripts/start-dev.ps1`

**Interfaces:**
- Consumes: `start-dev.ps1 -SkipBrowser`
- Produces: reachable API health endpoint and UI reverse proxy

- [ ] **Step 1: Start both services without opening the browser**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1 -SkipBrowser
```

Expected: dependency checks pass, both services become ready, and the launcher exits 0.

- [ ] **Step 2: Verify API, UI, and Vite proxy**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
(Invoke-WebRequest -UseBasicParsing http://localhost:5173).StatusCode
Invoke-RestMethod http://localhost:5173/api/v1/health
```

Expected: API and proxy return `status=ok`; UI returns HTTP 200.

- [ ] **Step 3: Verify idempotent repeat execution**

Run the launcher again with `-SkipBrowser`.

Expected: it reports both healthy services as reused and does not start or terminate
additional service processes.

- [ ] **Step 4: Run final structural verification**

Run the structural test once more and inspect `git diff --check`.

Expected: test exits 0 and Git reports no whitespace errors.
