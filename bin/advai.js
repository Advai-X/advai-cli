#!/usr/bin/env node
/**
 * advai — Node.js entry point.
 * After `npm install -g advai-cli`, the `advai` command routes
 * through this script to the Python core.
 *
 * Design:
 *   1) Prefer the private Python virtual environment created during npm postinstall.
 *   2) If the virtual environment is missing, try to recreate it once.
 *   3) Fall back to the bundled source tree for local development checkouts.
 */
const { spawn, spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");

const packageRoot = path.resolve(__dirname, "..");
const installerScript = path.join(__dirname, "install-python.js");

// ---- locate python3 ----
function findPython() {
  const candidates =
    process.platform === "win32"
      ? [
          { exe: "py", prefixArgs: ["-3"] },
          { exe: "python", prefixArgs: [] },
          { exe: "python3", prefixArgs: [] },
        ]
      : [
          { exe: "python3", prefixArgs: [] },
          { exe: "python", prefixArgs: [] },
        ];
  for (const candidate of candidates) {
    const r = spawnSync(
      candidate.exe,
      [
        ...candidate.prefixArgs,
        "-c",
        "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)",
      ],
      { stdio: "ignore" }
    );
    if (r.status === 0) return candidate;
  }
  return null;
}

// ---- locate advai/cli.py inside this npm package ----
function findLocalCli() {
  const candidate = path.join(packageRoot, "advai", "cli.py");
  if (fs.existsSync(candidate)) return candidate;
  return null;
}

function venvExecutable(name) {
  if (process.platform === "win32") {
    return path.join(packageRoot, "python-env", "Scripts", `${name}.exe`);
  }
  return path.join(packageRoot, "python-env", "bin", name);
}

function ensurePrivateEnvironment() {
  const advaiExe = venvExecutable("advai");
  if (fs.existsSync(advaiExe)) {
    return advaiExe;
  }

  if (!fs.existsSync(installerScript) || process.env.ADVAI_SKIP_PYTHON_INSTALL === "1") {
    return null;
  }

  const result = spawnSync(process.execPath, [installerScript], { stdio: "inherit" });
  if (result.status === 0 && fs.existsSync(advaiExe)) {
    return advaiExe;
  }

  return null;
}

const argv = process.argv.slice(2);

let child;
const privateAdvai = ensurePrivateEnvironment();
if (privateAdvai) {
  child = spawn(privateAdvai, argv, { stdio: "inherit" });
} else {
  const python = findPython();
  if (!python) {
    process.stderr.write(
      "advai requires Python 3.10+ and a working private environment. Reinstall the npm package after installing Python.\n"
    );
    process.exit(2);
  }

  const localCli = findLocalCli();
  if (localCli) {
    child = spawn(python.exe, [...python.prefixArgs, localCli, ...argv], {
      stdio: "inherit",
    });
  } else {
    process.stderr.write(
      "advai could not find its private Python environment. Try `npm rebuild -g advai-cli`.\n"
    );
    process.exit(1);
  }
}

child.on("exit", (code) => process.exit(code === null ? 1 : code));
child.on("error", (err) => {
  process.stderr.write("Failed to start advai: " + err.message + "\n");
  process.exit(1);
});
