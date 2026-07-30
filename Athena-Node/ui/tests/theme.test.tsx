import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { useTheme } from "../src/styles/ThemeContext";
import { ThemeProvider } from "../src/styles/ThemeProvider";
import { createTheme, THEME_STORAGE_KEY } from "../src/styles/theme";

function luminance(hex: string) {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)!
    .map((channel) => {
      const value = Number.parseInt(channel, 16) / 255;
      return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(foreground: string, background: string) {
  const foregroundLuminance = luminance(foreground);
  const backgroundLuminance = luminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

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

test("provides readable component tokens for the light application shell", () => {
  const lightTheme = createTheme("light");
  const layout = lightTheme.components?.Layout;
  const menu = lightTheme.components?.Menu;

  expect(layout?.headerBg).toMatch(/^#[0-9A-F]{6}$/i);
  expect(layout?.siderBg).toMatch(/^#[0-9A-F]{6}$/i);
  expect(menu?.itemBg).toMatch(/^#[0-9A-F]{6}$/i);
  expect(menu?.itemColor).toMatch(/^#[0-9A-F]{6}$/i);

  expect(contrast("#172033", layout!.headerBg as string)).toBeGreaterThanOrEqual(4.5);
  expect(contrast("#172033", layout!.siderBg as string)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(menu!.itemColor as string, menu!.itemBg as string)).toBeGreaterThanOrEqual(4.5);
});
