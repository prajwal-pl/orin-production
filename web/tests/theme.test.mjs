import assert from "node:assert/strict";
import test from "node:test";
import { resolveTheme } from "../lib/theme.ts";

test("saved choice wins over the operating system theme", () => {
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
});

test("first visit and invalid preferences follow the operating system", () => {
  assert.equal(resolveTheme(null, true), "dark");
  assert.equal(resolveTheme(null, false), "light");
  assert.equal(resolveTheme("invalid", true), "dark");
});
