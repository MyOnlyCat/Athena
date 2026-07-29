# Athena-Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deployable Athena child-node control plane with administrator login, encrypted SSH host management, browser terminal and SFTP file management, signed master-node task polling, real-time deployment reporting, documentation, and Docker deployment.

**Architecture:** Use one monorepo with a FastAPI/SQLAlchemy/AsyncSSH service in `api/`, a React/TypeScript/Vite application in `ui/`, shared operational documentation in `docs/`, and Nginx plus Docker Compose at the repository root. External SSH and master-node interactions are behind typed adapters so unit and integration tests can use deterministic fakes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite, AsyncSSH, APScheduler, HTTPX, React, TypeScript, Vite, Ant Design, xterm.js, Vitest, Pytest, Nginx, Docker Compose.

## Global Constraints

- `api/` and `ui/` live in the same repository, `MyOnlyCat/Athena-Nod`.
- SSH authentication supports username and password only.
- SSH passwords are encrypted at rest and never returned by read APIs.
- All authenticated users are administrators; there is no RBAC in version 1.
- The terminal page uses a three-column layout: server switcher, SSH terminal, remote file manager.
- The child node polls the master node every 60 seconds for deployment work.
- The master node builds artifacts; the child node only downloads, verifies, transfers, executes, and reports.
- SQLite is the only application database.
- New behavior is developed test-first.
- User-facing errors and labels are Chinese.
- The approved design is `docs/superpowers/specs/2026-07-29-athena-node-design.md`.

---

## Planned Repository Structure

```text
Athena-Nod/
├── api/
│   ├── alembic/
│   ├── app/
│   │   ├── api/v1/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── ui/
│   ├── src/
│   │   ├── app/
│   │   ├── features/
│   │   ├── shared/
│   │   └── styles/
│   ├── tests/
│   ├── Dockerfile
│   └── package.json
├── deploy/nginx.conf
├── docs/
│   ├── api/
│   ├── superpowers/
│   └── style-guide.md
├── .env.example
├── compose.yaml
├── CHANGELOG.md
├── README.md
└── TASKS.md
```

### Task 1: Monorepo Bootstrap and API Core

**Files:**
- Move: `api/docs/superpowers/specs/2026-07-29-athena-node-design.md` to `docs/superpowers/specs/2026-07-29-athena-node-design.md`
- Create: `.gitignore`
- Create: `api/pyproject.toml`
- Create: `api/alembic.ini`
- Create: `api/alembic/env.py`
- Create: `api/app/__init__.py`
- Create: `api/app/main.py`
- Create: `api/app/core/config.py`
- Create: `api/app/core/database.py`
- Create: `api/app/core/errors.py`
- Create: `api/app/core/logging.py`
- Create: `api/tests/conftest.py`
- Create: `api/tests/test_health.py`

**Interfaces:**
- Produces: `create_app(settings: Settings | None = None) -> FastAPI`
- Produces: `Settings` loaded from `ATHENA_` environment variables.
- Produces: SQLAlchemy async `Base`, engine factory, and request-scoped session dependency.
- Produces: error JSON `{code, message, request_id, details}`.

- [ ] **Step 1: Write the failing health and error-shape tests**

```python
def test_health_returns_service_state(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/missing")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "request_id", "details"}
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd api && python -m pytest tests/test_health.py -v`  
Expected: collection or import failure because `app.main` does not exist.

- [ ] **Step 3: Implement settings, app factory, database lifecycle, request ID, error handlers, and `/api/v1/health`**

Use an app factory so tests inject temporary settings. Configure SQLite WAL and foreign keys on connection. Refuse startup when the JWT secret or Fernet key is absent outside test mode.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd api && python -m pytest tests/test_health.py -v`  
Expected: 2 passed.

- [ ] **Step 5: Add Ruff and mypy configuration and run the core verification**

Run: `cd api && python -m ruff check app tests && python -m mypy app && python -m pytest -q`  
Expected: all commands exit 0.

- [ ] **Step 6: Commit**

```bash
git add .gitignore api docs
git commit -m "chore: bootstrap Athena Node API"
```

### Task 2: Authentication and Administrator Management

**Files:**
- Create: `api/app/models/user.py`
- Create: `api/app/models/revoked_token.py`
- Create: `api/app/schemas/auth.py`
- Create: `api/app/schemas/user.py`
- Create: `api/app/services/auth.py`
- Create: `api/app/services/users.py`
- Create: `api/app/api/v1/auth.py`
- Create: `api/app/api/v1/users.py`
- Create: `api/alembic/versions/0001_users.py`
- Create: `api/tests/test_auth.py`
- Create: `api/tests/test_users.py`

**Interfaces:**
- Produces: `AuthService.authenticate(username: str, password: str) -> TokenPair`
- Produces: `get_current_user() -> User`
- Produces: `UserService.create_user`, `set_active`, and `reset_password`.
- Consumes: async database session and `Settings`.

- [ ] **Step 1: Write failing authentication tests**

Cover valid login, wrong password, disabled user, expired token, logout revocation, bootstrap user creation, and the exact Chinese error codes.

```python
def test_disabled_user_cannot_login(client, disabled_user):
    response = client.post("/api/v1/auth/login", json={
        "username": disabled_user.username,
        "password": "ValidPassw0rd!"
    })
    assert response.status_code == 403
    assert response.json()["code"] == "USER_DISABLED"
```

- [ ] **Step 2: Verify authentication tests fail**

Run: `cd api && python -m pytest tests/test_auth.py -v`  
Expected: 404 responses because auth routes are missing.

- [ ] **Step 3: Implement Argon2 hashing, JWT access tokens, database revocation, bootstrap initialization, and login throttling**

JWT claims include `sub`, `jti`, `iat`, and `exp`. Login failures are counted by normalized username plus source IP; five failures lock the pair for 15 minutes.

- [ ] **Step 4: Verify authentication tests pass**

Run: `cd api && python -m pytest tests/test_auth.py -v`  
Expected: all authentication cases pass.

- [ ] **Step 5: Write failing user-management tests**

Cover create user, duplicate normalized username, disable and enable, reset password, rejection of self-disable, and rejection of disabling the last active user.

- [ ] **Step 6: Verify user-management tests fail**

Run: `cd api && python -m pytest tests/test_users.py -v`  
Expected: 404 responses because user routes are missing.

- [ ] **Step 7: Implement user routes and audit hooks**

Ensure password hashes never appear in schemas. Return `409` for duplicate names and `422` for password-policy violations.

- [ ] **Step 8: Run the complete API suite**

Run: `cd api && python -m pytest -q && python -m ruff check app tests`  
Expected: all tests pass and Ruff exits 0.

- [ ] **Step 9: Commit**

```bash
git add api
git commit -m "feat: add administrator authentication"
```

### Task 3: Encrypted Host Management and SSH Trust

**Files:**
- Create: `api/app/models/host.py`
- Create: `api/app/schemas/host.py`
- Create: `api/app/services/crypto.py`
- Create: `api/app/services/ssh.py`
- Create: `api/app/services/hosts.py`
- Create: `api/app/api/v1/hosts.py`
- Create: `api/alembic/versions/0002_hosts.py`
- Create: `api/tests/fakes/ssh.py`
- Create: `api/tests/test_crypto.py`
- Create: `api/tests/test_hosts.py`
- Create: `api/tests/test_ssh_trust.py`

**Interfaces:**
- Produces: `CredentialCipher.encrypt/decrypt`.
- Produces: `SSHClientProtocol.connect(host: HostConnection) -> SSHSession`.
- Produces: host CRUD and `POST /hosts/{id}/test`.
- Emits: `HostInventoryChanged` after committed create, update, delete, or fingerprint trust.

- [ ] **Step 1: Write and fail credential encryption tests**

Assert ciphertext differs from plaintext, round-trips correctly, rejects a different key, and never appears in serialized host responses.

Run: `cd api && python -m pytest tests/test_crypto.py -v`  
Expected: import failure for missing `CredentialCipher`.

- [ ] **Step 2: Implement Fernet credential encryption**

Accept a URL-safe base64 32-byte key from `ATHENA_CREDENTIAL_KEY`. Convert invalid tokens into `CREDENTIAL_DECRYPT_FAILED` without logging secrets.

- [ ] **Step 3: Write and fail host CRUD tests**

Cover validation, unique IP address, a single `is_local` host, password preservation when an edit omits `password`, and inventory-change events only after commit.

- [ ] **Step 4: Implement host model, schemas, service, migration, and REST routes**

Lists return test state and masked credential presence (`has_password: true`) but never ciphertext.

- [ ] **Step 5: Write and fail SSH connection and TOFU tests**

```python
async def test_changed_host_key_is_rejected(host_service, trusted_host, fake_ssh):
    fake_ssh.fingerprint = "SHA256:new"
    result = await host_service.test_connection(trusted_host.id)
    assert result.code == "SSH_HOST_KEY_CHANGED"
```

- [ ] **Step 6: Implement AsyncSSH adapter and stable error mapping**

Map DNS, timeout, refusal, authentication, first fingerprint, changed fingerprint, and success. A first fingerprint must be explicitly trusted before terminal, SFTP, or deployment use.

- [ ] **Step 7: Verify the host feature**

Run: `cd api && python -m pytest tests/test_crypto.py tests/test_hosts.py tests/test_ssh_trust.py -v`  
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add api
git commit -m "feat: add encrypted SSH host management"
```

### Task 4: Browser Terminal and SFTP API

**Files:**
- Create: `api/app/models/terminal_ticket.py`
- Create: `api/app/services/terminal.py`
- Create: `api/app/services/files.py`
- Create: `api/app/api/v1/terminal.py`
- Create: `api/app/api/v1/files.py`
- Create: `api/alembic/versions/0003_terminal_tickets.py`
- Create: `api/tests/test_terminal.py`
- Create: `api/tests/test_files.py`

**Interfaces:**
- Produces: `POST /api/v1/terminal/tickets` returning a 30-second one-use ticket.
- Produces: `WS /api/v1/terminal/ws/{host_id}`.
- Produces: SFTP list, mkdir, upload, download, rename, and delete endpoints.
- Consumes: trusted `SSHClientProtocol`.

- [ ] **Step 1: Write and fail terminal ticket and WebSocket protocol tests**

Cover one-use tickets, expiry, user ownership, five-session limit, input forwarding, output forwarding, resize, disconnect cleanup, and 30-minute idle close using a controllable clock.

- [ ] **Step 2: Implement terminal ticket and session services**

Use bounded queues so a slow browser cannot exhaust memory. WebSocket messages use:

```json
{"type":"resize","cols":120,"rows":36}
```

and:

```json
{"type":"output","data":"base64-encoded-bytes"}
```

- [ ] **Step 3: Write and fail SFTP behavior tests**

Cover normalized listing, 1 GiB limit, streamed upload/download, filename headers, mkdir, rename, recursive-delete rejection by default, explicit recursive delete, and audit records.

- [ ] **Step 4: Implement SFTP service and routes**

Never load complete files into memory. Validate empty paths and null bytes. Use remote permissions as the authority.

- [ ] **Step 5: Verify terminal and file APIs**

Run: `cd api && python -m pytest tests/test_terminal.py tests/test_files.py -v`  
Expected: all tests pass with no leaked tasks.

- [ ] **Step 6: Commit**

```bash
git add api
git commit -m "feat: add web terminal and SFTP APIs"
```

### Task 5: Master-Node Protocol and Inventory Synchronization

**Files:**
- Create: `api/app/models/node_state.py`
- Create: `api/app/schemas/master.py`
- Create: `api/app/services/signing.py`
- Create: `api/app/services/master_client.py`
- Create: `api/app/services/inventory_sync.py`
- Create: `api/app/workers/scheduler.py`
- Create: `api/alembic/versions/0004_node_state.py`
- Create: `api/tests/test_signing.py`
- Create: `api/tests/test_inventory_sync.py`
- Create: `docs/api/master-node-protocol.md`

**Interfaces:**
- Produces: `sign_request(method, path_with_query, timestamp, nonce, body) -> str`.
- Produces: `MasterClient.heartbeat`, `claim_tasks`, and `send_events`.
- Consumes: `HostInventoryChanged`.
- Schedules: heartbeat and task poll every 60 seconds.

- [ ] **Step 1: Write and fail deterministic HMAC test vectors**

Use fixed body bytes, timestamp, nonce, and expected SHA-256 HMAC. Include query-string ordering and empty-body cases.

- [ ] **Step 2: Implement the signing service**

Do not sign reconstructed JSON; sign the exact transmitted bytes.

- [ ] **Step 3: Write and fail inventory synchronization tests**

Cover startup heartbeat, periodic heartbeat, coalescing rapid host changes into one upload, password omission, offline retry, and last-success timestamp.

- [ ] **Step 4: Implement HTTPX master client, inventory synchronizer, and scheduler lifecycle**

Scheduler startup and shutdown belong to FastAPI lifespan. Only one scheduler may run per API process; deployment documentation fixes API workers to one.

- [ ] **Step 5: Write the master-node contract**

Document headers, canonical signature input, heartbeat request/response, task claim, task schema, event batches, error codes, idempotency, clock skew, nonce retention, example JSON, and a Python signature verification example.

- [ ] **Step 6: Verify protocol and inventory synchronization**

Run: `cd api && python -m pytest tests/test_signing.py tests/test_inventory_sync.py -v`  
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add api docs/api/master-node-protocol.md
git commit -m "feat: add master node synchronization protocol"
```

### Task 6: Deployment Task Executor and Progress Delivery

**Files:**
- Create: `api/app/models/deployment.py`
- Create: `api/app/schemas/deployment.py`
- Create: `api/app/services/artifacts.py`
- Create: `api/app/services/deployments.py`
- Create: `api/app/services/events.py`
- Create: `api/app/api/v1/tasks.py`
- Create: `api/alembic/versions/0005_deployments.py`
- Create: `api/tests/fakes/master.py`
- Create: `api/tests/test_artifacts.py`
- Create: `api/tests/test_deployments.py`
- Create: `api/tests/test_event_delivery.py`

**Interfaces:**
- Produces: `DeploymentCoordinator.accept_claims(tasks: list[ClaimedTask])`.
- Produces: `ArtifactService.download_and_verify`.
- Produces: persisted ordered `DeploymentEvent`.
- Produces: task list, detail, and event query endpoints.

- [ ] **Step 1: Write and fail artifact tests**

Cover HTTPS enforcement, streamed download, progress emission, SHA-256 match, mismatch cleanup, safe filename handling, timeout, and maximum artifact size.

- [ ] **Step 2: Implement artifact download and verification**

Write into a task-specific local temporary directory and atomically rename only after checksum success.

- [ ] **Step 3: Write and fail deployment coordination tests**

Cover duplicate `master_task_id`, unknown target IP, at most four parallel hosts, one active deployment per host, upload to a unique temporary name, SFTP atomic rename, working-directory execution, stdout/stderr order, exit code, partial target failure, and aggregate result.

- [ ] **Step 4: Implement task models, coordinator, per-host lock, and SSH execution**

Commands are passed unchanged to AsyncSSH. The working directory is validated as an absolute POSIX path and quoted independently by the adapter.

- [ ] **Step 5: Write and fail restart-recovery and event-delivery tests**

An `executing` target without an exit code becomes `manual_review`. Completed tasks only resend unacknowledged events. Verify 2, 4, 8, 16, 30-second backoff and contiguous acknowledgement.

- [ ] **Step 6: Implement durable event delivery and restart recovery**

Limit each output event to 16 KiB encoded payload and redact sensitive values before persistence.

- [ ] **Step 7: Add task query APIs and verify the full deployment path**

Run: `cd api && python -m pytest tests/test_artifacts.py tests/test_deployments.py tests/test_event_delivery.py -v`  
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add api
git commit -m "feat: execute and report deployment tasks"
```

### Task 7: React Foundation, Authentication, Dashboard, Hosts, and Users

**Files:**
- Create: `ui/package.json`
- Create: `ui/vite.config.ts`
- Create: `ui/tsconfig.json`
- Create: `ui/src/main.tsx`
- Create: `ui/src/app/router.tsx`
- Create: `ui/src/app/AppShell.tsx`
- Create: `ui/src/shared/api/client.ts`
- Create: `ui/src/shared/api/types.ts`
- Create: `ui/src/features/auth/*`
- Create: `ui/src/features/dashboard/*`
- Create: `ui/src/features/hosts/*`
- Create: `ui/src/features/users/*`
- Create: `ui/src/styles/theme.ts`
- Create: `ui/src/styles/global.css`
- Create: `ui/tests/auth.test.tsx`
- Create: `ui/tests/hosts.test.tsx`
- Create: `ui/tests/users.test.tsx`

**Interfaces:**
- Produces: authenticated route tree and typed API client.
- Produces: reusable status, error, confirmation, and loading components.
- Consumes: `/api/v1/auth`, `/users`, `/hosts`, and dashboard summary APIs.

- [ ] **Step 1: Bootstrap Vite test tooling and write failing auth-route tests**

Test redirect to login, Chinese login errors, successful navigation, and logout. Use MSW for HTTP behavior, not mocked feature components.

- [ ] **Step 2: Run auth test and verify RED**

Run: `cd ui && npm test -- --run tests/auth.test.tsx`  
Expected: import failure because the router and login page do not exist.

- [ ] **Step 3: Implement theme, app shell, API client, auth store, route guard, and login page**

Apply approved tokens: `#0B1020`, `#121A2B`, `#24324A`, `#5B8CFF`, `#2DD4A8`, `#F6C85F`, `#FF6B7A`, `#E8EEF8`, `#93A4BD`.

- [ ] **Step 4: Write failing host and user page tests**

Cover host validation, create/edit without password overwrite, connection result, fingerprint confirmation, current-node badge, user creation, reset password, and self-disable protection.

- [ ] **Step 5: Implement dashboard, host management, and user management**

Use query invalidation after mutations and show stable backend error messages with request IDs in expandable details.

- [ ] **Step 6: Verify UI features**

Run: `cd ui && npm test -- --run && npm run typecheck && npm run lint`  
Expected: all commands exit 0.

- [ ] **Step 7: Commit**

```bash
git add ui
git commit -m "feat: add admin and host management UI"
```

### Task 8: Three-Column Terminal, File Manager, Tasks, and Audit UI

**Files:**
- Create: `ui/src/features/terminal/TerminalPage.tsx`
- Create: `ui/src/features/terminal/ServerSwitcher.tsx`
- Create: `ui/src/features/terminal/TerminalPane.tsx`
- Create: `ui/src/features/terminal/FileManager.tsx`
- Create: `ui/src/features/terminal/useTerminalSession.ts`
- Create: `ui/src/features/tasks/*`
- Create: `ui/src/features/audit/*`
- Create: `ui/tests/terminal.test.tsx`
- Create: `ui/tests/files.test.tsx`
- Create: `ui/tests/tasks.test.tsx`

**Interfaces:**
- Consumes: terminal ticket HTTP endpoint, terminal WebSocket protocol, SFTP APIs, task APIs, and audit API.
- Produces: desktop three-column layout and mobile file drawer.

- [ ] **Step 1: Write and fail server-switch and terminal lifecycle tests**

Cover searchable server list, confirmation before switching a connected session, ticket creation, WebSocket connect, resize, output decode, disconnect, and reconnection error.

- [ ] **Step 2: Implement xterm.js session hook and three-column terminal layout**

Use a ref-owned terminal instance, fit addon on pane resize, and clean up terminal, WebSocket, observers, and listeners on every switch.

- [ ] **Step 3: Write and fail file-manager interaction tests**

Cover breadcrumb navigation, refresh, upload progress, download, mkdir, rename, delete confirmation, recursive-delete confirmation, and backend error display.

- [ ] **Step 4: Implement the SFTP file manager**

Desktop width allocation is 240 px left, flexible center, 360 px right. Below 960 px, the right pane becomes a drawer.

- [ ] **Step 5: Write and fail task/audit rendering tests**

Cover stage labels, progress, stdout/stderr distinction, result state, pagination, and audit details.

- [ ] **Step 6: Implement task and audit pages**

Poll active task detail every two seconds; stop polling terminal states.

- [ ] **Step 7: Verify the complete UI**

Run: `cd ui && npm test -- --run && npm run typecheck && npm run lint && npm run build`  
Expected: tests pass and production build exits 0.

- [ ] **Step 8: Commit**

```bash
git add ui
git commit -m "feat: add web SSH and file manager UI"
```

### Task 9: Documentation, Docker, Integration, and Preview

**Files:**
- Create: `api/Dockerfile`
- Create: `ui/Dockerfile`
- Create: `deploy/nginx.conf`
- Create: `compose.yaml`
- Create: `.env.example`
- Create: `TASKS.md`
- Create: `CHANGELOG.md`
- Create: `README.md`
- Create: `docs/api/local-api.md`
- Create: `docs/api/websocket-protocol.md`
- Create: `docs/api/openapi.json`
- Create: `docs/style-guide.md`
- Create: `api/tests/integration/test_release_flow.py`
- Create: `scripts/export-openapi.py`

**Interfaces:**
- Produces: `docker compose up --build` deployment on port 8080.
- Produces: local UI preview on port 5173 and API documentation on port 8000.
- Produces: master-node implementation contract and generated local OpenAPI.

- [ ] **Step 1: Write and fail the integration release-flow test**

Start a temporary SQLite database, fake master HTTP app, and AsyncSSH test server. Assert heartbeat inventory, claim, artifact checksum, SFTP placement, command output, event acknowledgement, and final success.

- [ ] **Step 2: Implement missing integration seams until the end-to-end test passes**

Run: `cd api && python -m pytest tests/integration/test_release_flow.py -v`  
Expected: one complete release-flow test passes.

- [ ] **Step 3: Generate OpenAPI and write interface documentation**

Run: `cd api && python ../scripts/export-openapi.py`  
Expected: deterministic `docs/api/openapi.json`.

Document every local endpoint, terminal WebSocket frame, environment variable, master-node request, response, signature example, retry rule, and task state.

- [ ] **Step 4: Add Dockerfiles, Nginx, Compose, and environment template**

Run API as a non-root user with one Uvicorn worker. Persist `/data`. Proxy `/api/` and `/api/v1/terminal/ws/` with WebSocket upgrade headers.

- [ ] **Step 5: Build and run container verification**

Run: `docker compose config`  
Expected: valid configuration.

Run: `docker compose build`  
Expected: both images build successfully.

Run: `docker compose up -d`  
Expected: services become healthy.

Run: `curl http://localhost:8080/api/v1/health`  
Expected: HTTP 200 with `"status":"ok"`.

- [ ] **Step 6: Complete task list, changelog, README, and style guide**

`TASKS.md` mirrors these nine tasks and records completion. `CHANGELOG.md` follows Keep a Changelog with version `0.1.0`. README includes setup, secrets, initial login, development, tests, preview, Docker, backup, and troubleshooting.

- [ ] **Step 7: Run fresh full verification**

Run: `cd api && python -m ruff check app tests && python -m mypy app && python -m pytest -q`  
Expected: zero failures.

Run: `cd ui && npm test -- --run && npm run typecheck && npm run lint && npm run build`  
Expected: zero failures and successful build.

Run: `docker compose config && docker compose ps`  
Expected: valid configuration and healthy services.

- [ ] **Step 8: Start development preview**

Start API bound to `0.0.0.0:8000` and UI bound to `0.0.0.0:5173`. Verify the actual LAN IPv4 address and open the UI in a browser. Report both URLs only after an HTTP request confirms they respond.

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "docs: add deployment and integration guides"
```

## Final Acceptance Checklist

- [ ] Current node and other hosts can be created with username/password SSH data.
- [ ] Saved SSH passwords are encrypted and omitted from API responses and logs.
- [ ] Administrators can test SSH connectivity and explicitly trust first-seen host fingerprints.
- [ ] The browser terminal switches servers and cleans up old connections.
- [ ] Remote files can be browsed, uploaded, downloaded, created, renamed, and deleted under SSH permissions.
- [ ] Users can log in/out and administrators can create, disable, enable, and reset other users.
- [ ] Startup and host changes cause master-node inventory reports.
- [ ] Task claim runs every 60 seconds and is idempotent.
- [ ] Artifacts are streamed, SHA-256 verified, transferred, and executed in the requested directory.
- [ ] Progress and redacted logs are durably and continuously reported.
- [ ] Interrupted executing commands become `manual_review` rather than rerun.
- [ ] SQLite data survives container restart.
- [ ] REST, WebSocket, master-node, style, task, changelog, and deployment docs exist.
- [ ] API tests, UI tests, type checks, linters, builds, integration test, and Docker health checks pass.
- [ ] Verified preview URLs are provided.

