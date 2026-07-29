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
