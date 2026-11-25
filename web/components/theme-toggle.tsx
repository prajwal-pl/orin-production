"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { resolveTheme, THEME_STORAGE_KEY, type Theme } from "@/lib/theme";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      let preference: string | null = null;
      try {
        preference = localStorage.getItem(THEME_STORAGE_KEY);
      } catch {
        // Browser storage may be disabled; the system theme still works.
      }
      const next = resolveTheme(preference, media.matches);
      document.documentElement.dataset.theme = next;
      setTheme(next);
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  function toggle() {
    const next =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Keep the selected theme for this page when storage is unavailable.
    }
  }

  return (
    <button
      className={`icon-button theme-toggle ${className}`.trim()}
      type="button"
      title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      aria-label={
        theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
      }
      onClick={toggle}
    >
      <Sun className="theme-icon-light" size={18} aria-hidden="true" />
      <Moon className="theme-icon-dark" size={18} aria-hidden="true" />
    </button>
  );
}
