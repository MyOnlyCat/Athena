import { ConfigProvider } from "antd";
import {
  type PropsWithChildren,
  useCallback,
  useEffect,
  useMemo,
  useState
} from "react";

import { ThemeContext } from "./ThemeContext";
import { createTheme, THEME_STORAGE_KEY, type ThemeMode } from "./theme";

function getInitialTheme(): ThemeMode {
  try {
    const savedTheme = localStorage.getItem(THEME_STORAGE_KEY);
    if (savedTheme === "light" || savedTheme === "dark") return savedTheme;
  } catch {
    // Storage access can be unavailable in privacy-restricted environments.
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeProvider({ children }: PropsWithChildren) {
  const [mode, setMode] = useState<ThemeMode>(getInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
  }, [mode]);

  const toggleTheme = useCallback(() => {
    setMode((currentMode) => {
      const nextMode = currentMode === "light" ? "dark" : "light";
      try {
        localStorage.setItem(THEME_STORAGE_KEY, nextMode);
      } catch {
        // Theme toggling remains available when storage is unavailable.
      }
      return nextMode;
    });
  }, []);

  const value = useMemo(() => ({ mode, toggleTheme }), [mode, toggleTheme]);
  return (
    <ThemeContext.Provider value={value}>
      <ConfigProvider theme={createTheme(mode)}>{children}</ConfigProvider>
    </ThemeContext.Provider>
  );
}
