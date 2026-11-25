import assert from "node:assert/strict";
import test from "node:test";

import { formatDate } from "../lib/format.ts";

test("SQLite UTC timestamps display at the viewer's local time", () => {
  assert.equal(
    formatDate("2026-11-25 16:00:00"),
    formatDate("2026-11-25T16:00:00Z"),
  );
  assert.equal(
    formatDate("2026-11-25T16:00:00"),
    formatDate("2026-11-25T16:00:00Z"),
  );
  assert.equal(
    formatDate("2026-11-25T21:30:00+05:30"),
    formatDate("2026-11-25T16:00:00Z"),
  );
});

test("Unix seconds and missing values are handled explicitly", () => {
  assert.equal(formatDate(1795622400), formatDate("2026-11-25T16:00:00Z"));
  assert.equal(formatDate(null), "—");
});
