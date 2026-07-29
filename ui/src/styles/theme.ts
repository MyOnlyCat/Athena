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
