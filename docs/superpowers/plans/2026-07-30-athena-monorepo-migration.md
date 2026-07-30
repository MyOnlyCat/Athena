# Athena Monorepo Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Athena-Node history while converting `G:\Athena` into the unified Athena repository, centralizing documentation, validating the moved project, and publishing it to `MyOnlyCat/Athena`.

**Architecture:** Promote the existing Athena-Node Git metadata to the Athena root, then record the physical directory reorganization as normal Git renames. Keep all runnable code under `Athena-Node`, represent the undeveloped master with an explicit README, and make root-level files and `docs/` the authoritative project documentation.

**Tech Stack:** Git, PowerShell 5.1+, Markdown, Docker Compose, Python 3.12/FastAPI/pytest, Node.js 22/React/Vitest/TypeScript/Vite

## Global Constraints

- Preserve every existing Athena-Node commit, author, timestamp, and reachable parent.
- Do not delete, force-push, or modify `MyOnlyCat/Athena-Nod`.
- Publish the unified repository only to `https://github.com/MyOnlyCat/Athena.git`.
- Never commit `.env`, secrets, tokens, databases, runtime logs, dependency directories, caches, or build output.
- `Athena-Master` remains documentation-only until implementation exists.
- Root `compose.yaml` runs only Athena-Node and uses paths below `Athena-Node/`.
- Detailed documentation lives below root `docs/`; component READMEs link to it.
- A validation command that was not run must not be reported as passing.

---

### Task 1: Preserve the untracked quick-development launcher

**Files:**
- Create: `ui/start-dev.cmd`
- Create: `ui/scripts/start-dev.ps1`
- Create: `ui/scripts/test-start-dev.ps1`
- Create: `ui/docs/superpowers/specs/2026-07-30-quick-dev-start-design.md`
- Create: `ui/docs/superpowers/plans/2026-07-30-quick-dev-start.md`
- Modify only if required by the launcher: `api/pyproject.toml`

**Interfaces:**
- Consumes: `ui/package.json`, `api/pyproject.toml`, Node.js/npm, Python 3.12+
- Produces: `ui/start-dev.cmd --self-test` and the PowerShell launcher behind it

- [ ] **Step 1: Confirm the untracked scope**

Run:

```powershell
git status --short
git diff -- api/pyproject.toml
```

Expected: only launcher files, their two documents, and `preview-*.log` files are
untracked; any `api/pyproject.toml` change must be reviewed before staging.

- [ ] **Step 2: Run the launcher structural test**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ui\scripts\test-start-dev.ps1
```

Expected: exit code 0 and output containing `SELF_TEST_OK`.

- [ ] **Step 3: Parse the launcher**

Run:

```powershell
powershell.exe -NoProfile -Command "$errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path '.\ui\scripts\start-dev.ps1'), [ref]$null, [ref]$errors); if ($errors.Count) { $errors | ForEach-Object Message; exit 1 }"
```

Expected: exit code 0 and no parser errors.

- [ ] **Step 4: Stage only durable development files**

Run:

```powershell
git add -- ui/start-dev.cmd ui/scripts/start-dev.ps1 ui/scripts/test-start-dev.ps1 ui/docs/superpowers/specs/2026-07-30-quick-dev-start-design.md ui/docs/superpowers/plans/2026-07-30-quick-dev-start.md
git status --short
```

Expected: the five durable paths are staged and all four `preview-*.log` files remain
untracked. Add `api/pyproject.toml` explicitly only if Step 1 proves the launcher
depends on an existing intentional change.

- [ ] **Step 5: Commit the launcher**

Run:

```powershell
git commit -m "feat: add quick development launcher"
```

Expected: a commit containing no logs, caches, databases, environment files, or
dependencies.

### Task 2: Promote the Git repository and reorganize code

**Files:**
- Move: `Athena-Node/.git` to `.git`
- Move: existing Node application files below `Athena-Node/`
- Move: `Athena-Node/.env.example` to `.env.example`
- Move: `Athena-Node/.gitignore` to `.gitignore`
- Move: `Athena-Node/compose.yaml` to `compose.yaml`
- Move and rewrite: `Athena-Node/README.md` to `README.md`
- Move and rewrite: `Athena-Node/TASKS.md` to `TASKS.md`
- Move and rewrite: `Athena-Node/CHANGELOG.md` to `CHANGELOG.md`
- Create: `Athena-Node/README.md`
- Create: `Athena-Master/README.md`

**Interfaces:**
- Consumes: Git repository at `G:\Athena\Athena-Node`, current commit SHA, empty `Athena-Master/api` and `Athena-Master/ui` directories
- Produces: Git repository rooted at `G:\Athena` with component code under `Athena-Node/`

- [ ] **Step 1: Record the recovery point and validate paths**

Run:

```powershell
git status -sb
git rev-parse HEAD
git branch --show-current
Resolve-Path .
Resolve-Path ..
```

Expected: the working directory resolves to `G:\Athena\Athena-Node`, its parent
resolves to `G:\Athena`, the launcher commit is present, and only ignored runtime
logs remain outside Git.

- [ ] **Step 2: Confirm the destination Git path is absent**

Run:

```powershell
Test-Path -LiteralPath 'G:\Athena\.git'
Test-Path -LiteralPath 'G:\Athena\Athena-Node\.git'
```

Expected: root `.git` is `False` and Node `.git` is `True`. Stop if both exist.

- [ ] **Step 3: Promote Git metadata**

Run from `G:\Athena`:

```powershell
Move-Item -LiteralPath 'G:\Athena\Athena-Node\.git' -Destination 'G:\Athena\.git'
git status -sb
```

Expected: Git now reports `G:\Athena` as the worktree. Existing tracked paths appear
deleted at the root and their physical copies appear below `Athena-Node/`; history
is unchanged.

- [ ] **Step 4: Move authoritative root files**

Move `.env.example`, `.gitignore`, `compose.yaml`, `README.md`, `TASKS.md`, and
`CHANGELOG.md` from `Athena-Node/` to `G:\Athena`. Verify each resolved source and
destination remains within `G:\Athena` before moving it.

Expected: the six files exist at the root and no duplicate remains in
`Athena-Node/`.

- [ ] **Step 5: Write component boundaries**

Create `Athena-Node/README.md` with:

- the Node role and current implementation status;
- local and Compose startup entry points;
- links to `../README.md`, `../docs/node/`, and `../docs/api/`.

Create `Athena-Master/README.md` with:

- the master node's intended orchestration role;
- an explicit “not implemented” status;
- no startup command or placeholder service claim.

Remove the empty `Athena-Master/api` and `Athena-Master/ui` directories only after
resolving both paths and confirming they contain no files.

### Task 3: Centralize documentation and repair configuration paths

**Files:**
- Create or move: `docs/node/file-transfers.md`
- Create or move: `docs/node/style-guide.md`
- Create or move: `docs/api/local-api.md`
- Create or move: `docs/api/master-node-protocol.md`
- Create or move: `docs/api/openapi.json`
- Create or move: `docs/api/websocket-protocol.md`
- Move: all existing `docs/superpowers/plans/*.md` to root `docs/superpowers/plans/`
- Move: all existing `docs/superpowers/specs/*.md` to root `docs/superpowers/specs/`
- Move: all existing `ui/docs/superpowers/plans/*.md` to root `docs/superpowers/plans/`
- Move: all existing `ui/docs/superpowers/specs/*.md` to root `docs/superpowers/specs/`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `TASKS.md`
- Modify: `CHANGELOG.md`
- Modify: `compose.yaml`
- Modify: documentation links affected by the move

**Interfaces:**
- Consumes: existing Node documentation and Compose build/mount paths
- Produces: one root documentation tree and a root Compose entry point

- [ ] **Step 1: Move Node documentation**

Move user-facing Node documents to `docs/node/`, API/protocol documents to
`docs/api/`, and every plan/spec to the corresponding root
`docs/superpowers/{plans,specs}/` directory. Resolve source and destination paths
before each directory move and stop on filename collisions instead of overwriting.

Expected: `Athena-Node/docs` and `Athena-Node/ui/docs` contain no authoritative
documents; every previous document exists once under root `docs/`.

- [ ] **Step 2: Expand root ignore rules**

Ensure `.gitignore` contains these effective patterns:

```gitignore
.env
**/.pytest_cache/
**/.ruff_cache/
**/.mypy_cache/
**/__pycache__/
*.py[cod]
*.db
*.db-shm
*.db-wal
*.egg-info/
**/.venv/
**/data/
**/node_modules/
**/dist/
*.tsbuildinfo
coverage/
.worktrees/
preview-*.log
```

Expected: all four existing preview logs are ignored by
`git check-ignore -v`.

- [ ] **Step 3: Rewrite project documentation**

Rewrite root `README.md` as the Athena system overview. State that Node is partially
developed and Master is not implemented, show the final directory tree, retain
accurate Node startup guidance, and link to each root document.

Update `TASKS.md` with separate repository, Node, and Master sections. Preserve
completed Node items, and leave Master implementation tasks unchecked.

Prepend a `2026-07-30` monorepo migration section to `CHANGELOG.md` without removing
the existing Node history.

- [ ] **Step 4: Repair Compose paths**

Update root `compose.yaml` so every relative build context, Dockerfile, bind mount,
and Nginx configuration path resolves below `Athena-Node/`. Do not add a Master
service.

- [ ] **Step 5: Check local Markdown links**

Run a repository script or a PowerShell link scan that extracts relative Markdown
links, strips anchors, resolves them relative to the source document, and fails for
any missing local target.

Expected: zero broken local documentation links.

- [ ] **Step 6: Stage the migration explicitly**

Run:

```powershell
git add -A -- . ':!Athena-Node/api/preview-api.log' ':!Athena-Node/api/preview-api.err.log' ':!Athena-Node/ui/preview-ui.log' ':!Athena-Node/ui/preview-ui.err.log'
git status --short
git diff --cached --stat
git diff --cached --check
```

Expected: Git reports renames/additions/modifications for the planned structure,
reports no logs, and reports no whitespace errors.

- [ ] **Step 7: Commit the monorepo structure**

Run:

```powershell
git commit -m "chore: migrate Athena to monorepo"
```

Expected: one reviewable structure commit following the launcher and design commits.

### Task 4: Verify the migrated repository

**Files:**
- Modify only if verification exposes a migration defect: files moved or rewritten in Tasks 2–3

**Interfaces:**
- Consumes: migrated root layout
- Produces: recorded validation evidence

- [ ] **Step 1: Verify repository history**

Run from `G:\Athena`:

```powershell
git status -sb
git log --oneline --decorate -10
git log --follow --oneline -- Athena-Node/api/app/main.py
```

Expected: clean worktree apart from ignored local logs, recent migration commits are
present, and `--follow` reaches commits predating the directory move.

- [ ] **Step 2: Validate Compose**

Run:

```powershell
docker compose config --quiet
```

Expected: exit code 0. Also verify every path referenced by `compose.yaml` exists.

- [ ] **Step 3: Verify the launcher after relocation**

Run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Athena-Node\ui\scripts\test-start-dev.ps1
powershell.exe -NoProfile -Command "$errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path '.\Athena-Node\ui\scripts\start-dev.ps1'), [ref]$null, [ref]$errors); if ($errors.Count) { $errors | ForEach-Object Message; exit 1 }"
```

Expected: self-test prints `SELF_TEST_OK`; syntax parsing exits 0.

- [ ] **Step 4: Run API validation**

Run from `G:\Athena\Athena-Node\api`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
```

Expected: all tests pass and Ruff reports no violations. If the existing virtual
environment is absent, create it with Python 3.12 and install `.[dev]` before
retrying once.

- [ ] **Step 5: Run UI validation**

Run from `G:\Athena\Athena-Node\ui`:

```powershell
npm test -- --run
npm run typecheck
npm run lint
npm run build
```

Expected: tests, type checking, lint, and production build all exit 0. If
`node_modules` is absent, run `npm ci` before retrying once.

- [ ] **Step 6: Commit migration-only fixes**

If Steps 1–5 exposed a relocation defect, stage only the affected files, rerun the
failed check plus `git diff --cached --check`, and commit:

```powershell
git commit -m "fix: repair monorepo migration paths"
```

Expected: clean status after the fix. Do not create an empty commit when no fix was
needed.

### Task 5: Publish the unified repository

**Files:**
- Modify Git remote configuration only

**Interfaces:**
- Consumes: clean verified local branch and GitHub repository `MyOnlyCat/Athena`
- Produces: `main` on `https://github.com/MyOnlyCat/Athena.git`

- [ ] **Step 1: Recheck the target repository**

Use the connected GitHub repository metadata API immediately before publishing.

Expected: `MyOnlyCat/Athena` is still accessible with push permission. If it is no
longer empty, stop and inspect its default branch before pushing.

- [ ] **Step 2: Preserve the legacy remote**

Run:

```powershell
git remote rename origin athena-node-legacy
git remote add origin https://github.com/MyOnlyCat/Athena.git
git remote -v
```

Expected: `origin` points only to `MyOnlyCat/Athena`; `athena-node-legacy` points
only to `MyOnlyCat/Athena-Nod`.

- [ ] **Step 3: Confirm branch and authentication**

Because the target repository is empty, rename the verified local branch to
`main`:

```powershell
git branch -m main
git ls-remote origin
```

Expected: authentication succeeds and the empty repository returns no refs. If Git
credentials are unavailable, install/authenticate GitHub CLI or use an approved
credential flow before continuing.

- [ ] **Step 4: Push the initial main branch**

Run:

```powershell
git push -u origin main
```

Expected: a non-force initial push creates `main` and establishes upstream
tracking. Never use `--force`.

- [ ] **Step 5: Verify the remote commit**

Fetch repository metadata and the published head commit through the connected
GitHub API, then compare it with:

```powershell
git rev-parse HEAD
git status -sb
```

Expected: local `HEAD`, remote `main`, and GitHub's published head SHA match; the
worktree is clean. No pull request is needed for the first branch of an empty
repository.
