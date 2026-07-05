#!/usr/bin/env node
const { spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const packageRoot = path.resolve(__dirname, "..");
const packageJson = require(path.join(packageRoot, "package.json"));
const packageVersion = packageJson.version;
const packageSpec = process.env.ADVAI_PIP_INSTALL_SPEC || `advai-cli==${packageVersion}`;
const venvDir = path.join(packageRoot, "python-env");

function log(message) {
  process.stdout.write(`[advai] ${message}\n`);
}

function fail(message) {
  process.stderr.write(`[advai] ${message}\n`);
  process.exit(1);
}

function getPythonCandidates() {
  if (process.platform === "win32") {
    return [
      { command: "py", prefixArgs: ["-3"] },
      { command: "python", prefixArgs: [] },
      { command: "python3", prefixArgs: [] },
    ];
  }

  return [
    { command: "python3", prefixArgs: [] },
    { command: "python", prefixArgs: [] },
  ];
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    stdio: options.stdio || "pipe",
    cwd: options.cwd || packageRoot,
    env: options.env || process.env,
  });
}

function findPython() {
  for (const candidate of getPythonCandidates()) {
    const versionCheck = run(candidate.command, [
      ...candidate.prefixArgs,
      "-c",
      "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)",
    ]);
    if (versionCheck.status === 0) {
      return candidate;
    }
  }
  return null;
}

function venvPythonPath() {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", "python.exe");
  }
  return path.join(venvDir, "bin", "python");
}

function advaiExecutablePath() {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", "advai.exe");
  }
  return path.join(venvDir, "bin", "advai");
}

function ensureVenv(python) {
  const pythonPath = venvPythonPath();
  if (fs.existsSync(pythonPath)) {
    return;
  }

  log(`Creating private Python environment with ${python.command}`);
  const result = run(
    python.command,
    [...python.prefixArgs, "-m", "venv", venvDir],
    { stdio: "inherit" }
  );
  if (result.status !== 0) {
    fail("Failed to create the private Python environment.");
  }
}

function installPackage() {
  const pythonPath = venvPythonPath();
  const pipUpgrade = run(
    pythonPath,
    ["-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
    { stdio: "inherit" }
  );
  if (pipUpgrade.status !== 0) {
    fail("Failed to prepare pip inside the private Python environment.");
  }

  log(`Installing ${packageSpec} into the private Python environment`);
  const installResult = run(
    pythonPath,
    [
      "-m",
      "pip",
      "install",
      "--upgrade",
      "--disable-pip-version-check",
      packageSpec,
    ],
    { stdio: "inherit" }
  );
  if (installResult.status !== 0) {
    fail(
      `Failed to install ${packageSpec}. Make sure the matching version is available on PyPI.`
    );
  }

  if (!fs.existsSync(advaiExecutablePath())) {
    fail("The private Python environment was created, but the advai executable is missing.");
  }
}

function main() {
  if (process.env.ADVAI_SKIP_PYTHON_INSTALL === "1") {
    log("Skipping private Python environment setup because ADVAI_SKIP_PYTHON_INSTALL=1");
    return;
  }

  const python = findPython();
  if (!python) {
    fail("Python 3.10+ is required. Please install Python 3 and rerun npm install.");
  }

  ensureVenv(python);
  installPackage();
}

main();
