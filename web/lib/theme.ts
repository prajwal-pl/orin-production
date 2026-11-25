export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "orin-theme";

export function resolveTheme(
  preference: string | null,
  systemDark: boolean,
): Theme {
  return preference === "light" || preference === "dark"
    ? preference
    : systemDark
      ? "dark"
      : "light";
}
