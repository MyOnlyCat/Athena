# UI Theme and SSH Test Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复控制台可读性与布局问题，提供可持久化的日间/夜间模式，并让首次 SSH 指纹信任流程自动复测并显示最终连接状态。

**Architecture:** 新增一个只负责主题状态和 Ant Design 配置的 `ThemeProvider`，使用语义 CSS 变量驱动自定义区域。现有页面组件只消费主题切换接口；SSH 修复限定在主机页面的“信任后复测”编排，不改 API 路由、数据库或底层 AsyncSSH 连接实现。

**Tech Stack:** React 19、TypeScript 5.8、Ant Design 5、TanStack Query 5、Vitest 3、Testing Library、FastAPI、Pytest、AsyncSSH。

## Global Constraints

- 菜单和任务页用户可见文案使用“当前任务”，首页使用“最近任务”和“暂无任务”。
- 首次无保存偏好时跟随 `prefers-color-scheme`，用户主动选择后保存 `light` 或 `dark`。
- 网页终端保持深色，不随页面主题切换。
- 不修改任务 API、SSH API、数据库字段、凭据格式或 SSH 指纹安全规则。
- 不把真实 SSH 密码写入源代码、测试、计划、日志或提交记录。
- 每项生产代码修改前必须先运行对应失败测试。

---

## File Responsibility Map

- `src/styles/theme.ts`: 只定义 `ThemeMode`、主题存储键与 Ant Design 明暗主题配置。
- `src/styles/ThemeProvider.tsx`: 只负责主题初始化、持久化、根节点属性和 React 上下文。
- `src/styles/global.css`: 使用语义变量呈现自定义布局和组件可读性，不保存主题状态。
- `src/main.tsx`: 把主题 Provider 接入应用根节点。
- `src/app/AppShell.tsx`: 顶栏用户信息、主题按钮和侧边栏菜单文案。
- `src/features/dashboard/DashboardPage.tsx`: 首页任务文案。
- `src/features/tasks/TasksPage.tsx`: 当前任务页标题。
- `src/features/hosts/HostsPage.tsx`: SSH 测试、指纹确认、信任后复测和查询刷新。
- `src/shared/api/types.ts`: 定义 SSH 测试响应的精确类型。
- `src/shared/api/client.ts`: 为 `hostsApi.test` 提供该响应类型，不编排 UI 流程。
- `tests/theme.test.tsx`: 主题初始化、切换与持久化行为。
- `tests/app-shell.test.tsx`: 顶栏和菜单行为。
- `tests/tasks.test.tsx`: 当前任务页面文案。
- `tests/dashboard.test.tsx`: 首页任务文案。
- `tests/hosts-page.test.tsx`: 指纹确认后的信任与复测顺序。

---

### Task 1: Theme State and Ant Design Configuration

**Files:**
- Create: `src/styles/ThemeProvider.tsx`
- Modify: `src/styles/theme.ts`
- Modify: `src/main.tsx`
- Create: `tests/theme.test.tsx`

**Interfaces:**
- Produces: `type ThemeMode = "light" | "dark"`
- Produces: `const THEME_STORAGE_KEY = "athena_theme"`
- Produces: `createTheme(mode: ThemeMode): ThemeConfig`
- Produces: `ThemeProvider({ children }: PropsWithChildren): JSX.Element`
- Produces: `useTheme(): { mode: ThemeMode; toggleTheme(): void }`

- [ ] **Step 1: Write the failing theme tests**

Create `tests/theme.test.tsx` with a small consumer:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ThemeProvider, useTheme } from "../src/styles/ThemeProvider";
import { THEME_STORAGE_KEY } from "../src/styles/theme";

function Consumer() {
  const { mode, toggleTheme } = useTheme();
  return <button onClick={toggleTheme}>{mode}</button>;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  delete document.documentElement.dataset.theme;
});

test("uses the system theme when no preference is stored", () => {
  vi.spyOn(window, "matchMedia").mockReturnValue({
    matches: true
  } as MediaQueryList);

  render(<ThemeProvider><Consumer /></ThemeProvider>);

  expect(screen.getByRole("button", { name: "dark" })).toBeInTheDocument();
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
});

test("restores a saved theme and persists an explicit toggle", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  const user = userEvent.setup();

  render(<ThemeProvider><Consumer /></ThemeProvider>);
  await user.click(screen.getByRole("button", { name: "light" }));

  expect(screen.getByRole("button", { name: "dark" })).toBeInTheDocument();
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
npm test -- --run tests/theme.test.tsx
```

Expected: FAIL because `src/styles/ThemeProvider.tsx` and the named exports do not exist.

- [ ] **Step 3: Implement the minimal theme model and provider**

In `src/styles/theme.ts`, export the exact public interface and return a light or dark Ant Design configuration:

```ts
import { theme as antdTheme, type ThemeConfig } from "antd";

export type ThemeMode = "light" | "dark";
export const THEME_STORAGE_KEY = "athena_theme";

export function createTheme(mode: ThemeMode): ThemeConfig {
  const dark = mode === "dark";
  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: "#5B8CFF",
      colorSuccess: "#1FA980",
      colorWarning: "#D99A16",
      colorError: dark ? "#FF7A88" : "#D9363E",
      colorBgBase: dark ? "#0B1020" : "#F4F7FB",
      colorBgContainer: dark ? "#121A2B" : "#FFFFFF",
      colorBorder: dark ? "#31415D" : "#CBD5E1",
      colorText: dark ? "#F3F6FB" : "#172033",
      colorTextSecondary: dark ? "#B4C0D2" : "#526078",
      colorTextPlaceholder: dark ? "#8796AC" : "#66758C",
      borderRadius: 8,
      controlHeight: 36,
      fontFamily:
        '"Inter", "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif'
    }
  };
}
```

In `src/styles/ThemeProvider.tsx`, initialize from a valid saved value or `matchMedia`, catch storage failures, set `data-theme` in an effect, and save only inside `toggleTheme`.

In `src/main.tsx`, remove the static `ConfigProvider` and wrap the existing Ant Design `App` with `ThemeProvider`.

- [ ] **Step 4: Run the theme tests and verify GREEN**

Run:

```powershell
npm test -- --run tests/theme.test.tsx
```

Expected: 2 tests PASS.

- [ ] **Step 5: Run type checking**

Run:

```powershell
npm run typecheck
```

Expected: exit code 0.

- [ ] **Step 6: Commit the theme state**

```powershell
git add ui/src/styles/theme.ts ui/src/styles/ThemeProvider.tsx ui/src/main.tsx ui/tests/theme.test.tsx
git commit -m "feat(ui): add persistent light and dark themes"
```

---

### Task 2: Header Alignment, Readability, Menu and Task Copy

**Files:**
- Modify: `src/app/AppShell.tsx`
- Modify: `src/styles/global.css`
- Modify: `src/features/dashboard/DashboardPage.tsx`
- Modify: `src/features/tasks/TasksPage.tsx`
- Create: `tests/app-shell.test.tsx`
- Create: `tests/dashboard.test.tsx`
- Modify: `tests/tasks.test.tsx`

**Interfaces:**
- Consumes: `useTheme(): { mode: ThemeMode; toggleTheme(): void }`
- Produces: a theme button with accessible names `切换到日间模式` or `切换到夜间模式`

- [ ] **Step 1: Write failing shell and copy tests**

In `tests/app-shell.test.tsx`, mock only the authentication hook and render the real shell inside `MemoryRouter`:

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { AppShell } from "../src/app/AppShell";
import { ThemeProvider } from "../src/styles/ThemeProvider";

vi.mock("../src/features/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", username: "alice" },
    logout: vi.fn()
  })
}));

test("renders aligned user identity, theme control, and current-task navigation", () => {
  render(
    <ThemeProvider>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </ThemeProvider>
  );

  expect(screen.getByText("alice")).toBeInTheDocument();
  expect(screen.getByText("管理员")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /切换到.+模式/ })).toBeInTheDocument();
  expect(screen.getByText("当前任务")).toBeInTheDocument();
  expect(document.querySelector(".ant-menu-item-divider")).not.toBeInTheDocument();
});
```

Extend `tests/tasks.test.tsx` to render `TasksPage` with the existing test providers and assert `当前任务`. Create `tests/dashboard.test.tsx` and assert `最近任务` plus `暂无任务` for an empty task query.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
npm test -- --run tests/app-shell.test.tsx tests/tasks.test.tsx tests/dashboard.test.tsx
```

Expected: FAIL on missing theme control and old “发布任务” copy.

- [ ] **Step 3: Implement the shell and copy changes**

In `AppShell.tsx`:

- import `BulbOutlined` and `MoonOutlined`;
- consume `useTheme`;
- render the theme button immediately before the avatar;
- change the task label to `当前任务`;
- remove `{ type: "divider" }`.

In the task and dashboard pages, replace only the user-visible strings defined in Global Constraints.

- [ ] **Step 4: Introduce semantic theme variables and fix contrast**

At the start of `global.css`, define dark defaults and light overrides:

```css
:root,
:root[data-theme="dark"] {
  --page-bg: #0b1020;
  --panel-bg: #121a2b;
  --panel-soft: #111a2c;
  --panel-raised: #101827;
  --border: #31415d;
  --border-soft: #24324a;
  --text: #f3f6fb;
  --text-secondary: #b4c0d2;
  --text-muted: #8796ac;
  --input-placeholder: #8796ac;
  --error-text: #ffd7dc;
  --error-bg: #4a1720;
  --error-border: #a83d4b;
  --shadow: rgba(0, 0, 0, .22);
}

:root[data-theme="light"] {
  --page-bg: #f4f7fb;
  --panel-bg: #ffffff;
  --panel-soft: #f7f9fc;
  --panel-raised: #eef3f9;
  --border: #cbd5e1;
  --border-soft: #d9e1eb;
  --text: #172033;
  --text-secondary: #526078;
  --text-muted: #66758c;
  --input-placeholder: #66758c;
  --error-text: #8f1d28;
  --error-bg: #fff1f2;
  --error-border: #e9a6ad;
  --shadow: rgba(42, 57, 78, .12);
}
```

Replace hardcoded custom surface/text/border colors with these variables. Keep `.terminal-page`, `.terminal-center`, `.xterm-container`, `.server-switcher`, `.file-manager` and terminal log surfaces explicitly dark.

Add the focused readability and alignment rules:

```css
.app-header { line-height: normal; }
.user-summary { display: grid; gap: 2px; line-height: 1.2; }
.user-summary strong { color: var(--text); }
.user-summary span { color: var(--text-muted); font-size: 11px; }
.ant-input::placeholder,
.ant-input-number-input::placeholder { color: var(--input-placeholder); opacity: 1; }
.ant-input-prefix,
.ant-input-password-icon { color: var(--text-secondary); }
.ant-alert-error {
  color: var(--error-text);
  border-color: var(--error-border);
  background: var(--error-bg);
}
.ant-alert-error .ant-alert-message,
.ant-alert-error .ant-alert-description,
.ant-alert-error .ant-alert-icon { color: var(--error-text); }
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
npm test -- --run tests/app-shell.test.tsx tests/tasks.test.tsx tests/dashboard.test.tsx
```

Expected: all focused tests PASS.

- [ ] **Step 6: Run lint and type checking**

Run:

```powershell
npm run lint
npm run typecheck
```

Expected: both exit code 0.

- [ ] **Step 7: Commit the visual and copy changes**

```powershell
git add ui/src/app/AppShell.tsx ui/src/styles/global.css ui/src/features/dashboard/DashboardPage.tsx ui/src/features/tasks/TasksPage.tsx ui/tests/app-shell.test.tsx ui/tests/dashboard.test.tsx ui/tests/tasks.test.tsx
git commit -m "fix(ui): improve theme readability and navigation copy"
```

---

### Task 3: Trust SSH Fingerprint and Retest

**Files:**
- Modify: `src/shared/api/types.ts`
- Modify: `src/shared/api/client.ts`
- Modify: `src/features/hosts/HostsPage.tsx`
- Create: `tests/hosts-page.test.tsx`

**Interfaces:**
- Produces: `interface SSHTestResult { status: string; code: string; message: string; fingerprint: string | null }`
- Produces: `hostsApi.test(id: string): Promise<SSHTestResult>`
- Consumes: existing `hostsApi.trust(id: string, fingerprint: string): Promise<Host>`

- [ ] **Step 1: Read the good-test rules before changing tests**

Read the complete `superpowers:test-driven-development/writing-good-tests.md` reference and apply its behavior-first assertions to this task.

- [ ] **Step 2: Write the failing host-page test**

Create `tests/hosts-page.test.tsx` using a real QueryClient and Ant Design `App`, while mocking only the network boundary. Configure:

```ts
hostsApi.list
  .mockResolvedValue([host]);
hostsApi.test
  .mockResolvedValueOnce({
    status: "pending_trust",
    code: "SSH_HOST_KEY_UNTRUSTED",
    message: "请确认主机指纹",
    fingerprint: "SHA256:first"
  })
  .mockResolvedValueOnce({
    status: "success",
    code: "SSH_CONNECTED",
    message: "SSH 连接成功",
    fingerprint: "SHA256:first"
  });
hostsApi.trust.mockResolvedValue({
  ...host,
  host_key_fingerprint: "SHA256:first"
});
```

Render `HostsPage`, click the row’s `测试连接` control, confirm `信任此指纹`, then assert:

```ts
expect(hostsApi.trust).toHaveBeenCalledWith("host-1", "SHA256:first");
expect(hostsApi.test).toHaveBeenCalledTimes(2);
expect(hostsApi.trust.mock.invocationCallOrder[0])
  .toBeLessThan(hostsApi.test.mock.invocationCallOrder[1]);
expect(await screen.findByText("SSH 连接成功")).toBeInTheDocument();
```

Add a second test where the second `test` response is `failed`, and assert the returned failure message is shown after the trust operation.

- [ ] **Step 3: Run the host-page tests and verify RED**

Run:

```powershell
npm test -- --run tests/hosts-page.test.tsx
```

Expected: FAIL because the current `onOk` only saves the fingerprint and does not await a second connection test.

- [ ] **Step 4: Add the SSH response type**

Add `SSHTestResult` to `src/shared/api/types.ts`. Type `hostsApi.test` in `client.ts` as:

```ts
test: async (id: string) =>
  (await api.post<SSHTestResult>(`/hosts/${id}/test`)).data,
```

- [ ] **Step 5: Implement trust-then-retest in HostsPage**

Extract one local helper which displays the final result:

```ts
function showTestResult(result: SSHTestResult) {
  message[result.status === "success" ? "success" : "error"](result.message);
}
```

For untrusted or changed fingerprints, make `onOk` async:

```ts
onOk: async () => {
  await hostsApi.trust(host.id, result.fingerprint!);
  const verified = await hostsApi.test(host.id);
  showTestResult(verified);
  await client.invalidateQueries({ queryKey: ["hosts"] });
}
```

For non-fingerprint results, call the same `showTestResult`. Move invalidation so it occurs after the completed branch rather than racing the modal confirmation.

- [ ] **Step 6: Run the host-page tests and verify GREEN**

Run:

```powershell
npm test -- --run tests/hosts-page.test.tsx
```

Expected: both trust/retest tests PASS.

- [ ] **Step 7: Run all host-related UI and API tests**

Run:

```powershell
npm test -- --run tests/hosts.test.tsx tests/hosts-page.test.tsx
& 'G:\Athena\Athena-Node\api\.venv\Scripts\python.exe' -m pytest tests/test_hosts.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 8: Commit the SSH UI flow fix**

```powershell
git add ui/src/shared/api/types.ts ui/src/shared/api/client.ts ui/src/features/hosts/HostsPage.tsx ui/tests/hosts-page.test.tsx
git commit -m "fix(ui): retest SSH after trusting host fingerprint"
```

---

### Task 4: Full Verification and Real SSH Check

**Files:**
- Verify only; do not add credentials or generated logs to Git.

**Interfaces:**
- Consumes all preceding tasks.
- Produces fresh verification evidence for completion.

- [ ] **Step 1: Run the complete UI verification suite**

Run:

```powershell
npm test -- --run
npm run lint
npm run typecheck
npm run build
```

Expected: every command exits 0 with no failing tests or TypeScript/ESLint errors.

- [ ] **Step 2: Run the complete API verification suite**

Run from `G:\Athena\Athena-Node\api`:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' -m mypy app
```

Expected: every command exits 0.

- [ ] **Step 3: Verify the real SSH connection without persisting the password**

Use the credential supplied in the conversation only in the one-off process invocation. Connect to `192.168.50.198:22` with `AsyncSSHClient`, assert the result code is `SSH_CONNECTED`, and compare the returned fingerprint with the previously observed `SHA256:KnZfMSI8dKjcq7CS0r8628bh/NHKjzjz3/8G4fUqI64`.

Expected: connection succeeds and the fingerprint matches. Do not print or store the password.

- [ ] **Step 4: Review the requirement checklist and repository diff**

Run:

```powershell
git status --short
git diff --check HEAD~3..HEAD
git diff --stat HEAD~3..HEAD
```

Confirm:

- top-right login identity is vertically aligned;
- placeholders and error alerts are readable in both themes;
- all requested task copy is updated;
- the menu divider is absent;
- theme preference persists;
- SSH trust is followed by a final connection result;
- unrelated pre-existing untracked files remain untouched.

- [ ] **Step 5: Prepare the completion handoff**

Report exact UI/API test counts, build/lint/type-check results, real SSH fingerprint verification, changed files, and any pre-existing unrelated worktree entries. Do not claim completion unless every fresh verification result supports it.
