import { createContext, useContext } from "react";

import type { ThemeMode } from "./theme";

export type ThemeContextValue = {
  mode: ThemeMode;
  toggleTheme(): void;
};

export const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function useTheme(): ThemeContextValue {
  const theme = useContext(ThemeContext);
  if (!theme) throw new Error("useTheme must be used within a ThemeProvider");
  return theme;
}
