import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(
  new URL("../styles/foundation.css", import.meta.url),
  "utf8",
);

function token(name) {
  const match = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, "i"));
  assert.ok(match, `Missing ${name} design token`);
  return match[1];
}

function luminance(hex) {
  const channels = [1, 3, 5].map(
    (offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255,
  );
  const linear = channels.map((value) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
}

function contrast(first, second) {
  const [lighter, darker] = [luminance(first), luminance(second)].sort(
    (a, b) => b - a,
  );
  return (lighter + 0.05) / (darker + 0.05);
}

test("core reading and action colors meet normal-text contrast", () => {
  for (const foreground of ["ink", "ink-soft", "muted", "quiet", "accent"]) {
    for (const background of ["paper", "canvas"]) {
      assert.ok(
        contrast(token(foreground), token(background)) >= 4.5,
        `${foreground} on ${background}`,
      );
    }
  }
  assert.ok(contrast(token("sidebar-text"), token("sidebar")) >= 4.5);
  assert.ok(
    contrast("#ffffff", token("accent")) >= 4.5,
    "primary button label",
  );
});

test("motion has a reduced-motion fallback", () => {
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
});
