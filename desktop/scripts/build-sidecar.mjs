import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const desktop = resolve(import.meta.dirname, "..");
const root = resolve(desktop, "..");
const triple = execFileSync("rustc", ["--print", "host-tuple"], {
  encoding: "utf8",
}).trim();
const extension = process.platform === "win32" ? ".exe" : "";
const output = resolve(desktop, "src-tauri", "binaries");

execFileSync("npm", ["run", "build"], {
  cwd: resolve(root, "web"),
  stdio: "inherit",
});
execFileSync(
  "uv",
  [
    "run",
    "pyinstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name",
    "orin-runtime",
    "--paths",
    root,
    "--add-data",
    `${resolve(root, "web", "out")}${process.platform === "win32" ? ";" : ":"}web/out`,
    "--add-data",
    `${resolve(root, "evaluation", "fixtures")}${process.platform === "win32" ? ";" : ":"}evaluation/fixtures`,
    "--distpath",
    resolve(desktop, "build", "sidecar"),
    "--workpath",
    resolve(desktop, "build", "pyinstaller"),
    "--specpath",
    resolve(desktop, "build"),
    resolve(desktop, "sidecar.py"),
  ],
  { cwd: root, stdio: "inherit" },
);

mkdirSync(output, { recursive: true });
copyFileSync(
  resolve(desktop, "build", "sidecar", `orin-runtime${extension}`),
  resolve(output, `orin-runtime-${triple}${extension}`),
);
