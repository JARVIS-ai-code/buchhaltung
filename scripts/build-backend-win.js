#!/usr/bin/env node
const { existsSync } = require("fs");
const { mkdirSync } = require("fs");
const { join, resolve } = require("path");
const { spawnSync } = require("child_process");

const root = resolve(__dirname, "..");
const distDir = join(root, "dist");
const backendDistDir = join(distDir, "backend");
const backendExe = join(backendDistDir, "JarvisBuchhaltungBackend.exe");
const versionJson = join(root, "version.json");

function run(command, args, label) {
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    shell: false
  });
  if (result.error) {
    throw new Error(`${label} fehlgeschlagen: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`${label} fehlgeschlagen mit Exit-Code ${result.status}`);
  }
}

function tryPython(candidates, args, label) {
  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, [...candidate.prefix, ...args], {
      cwd: root,
      stdio: "inherit",
      shell: false
    });
    if (!result.error && result.status === 0) {
      return candidate;
    }
  }
  throw new Error(`${label} konnte nicht ausgeführt werden.`);
}

function main() {
  if (process.platform !== "win32") {
    console.error("Dieses Skript muss auf Windows ausgeführt werden.");
    process.exit(1);
  }

  const pythonCandidates = [
    { command: "py", prefix: ["-3"] },
    { command: "python", prefix: [] }
  ];

  mkdirSync(distDir, { recursive: true });
  mkdirSync(backendDistDir, { recursive: true });
  if (!existsSync(versionJson)) {
    throw new Error(`version.json nicht gefunden: ${versionJson}`);
  }

  const python = tryPython(pythonCandidates, ["--version"], "Python");
  run(python.command, [...python.prefix, "-m", "pip", "install", "--upgrade", "pip"], "pip upgrade");
  run(python.command, [...python.prefix, "-m", "pip", "install", "pyinstaller"], "pyinstaller install");

  const pyinstallerArgs = [
    ...python.prefix,
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name",
    "JarvisBuchhaltungBackend",
    "--distpath",
    "dist/backend",
    "--workpath",
    "dist/.pyi-work",
    "--specpath",
    "dist/.pyi-spec",
    "--paths",
    ".",
    "--add-data",
    `${versionJson};.`,
    "app_backend.py"
  ];

  run(python.command, pyinstallerArgs, "Backend-PyInstaller-Build");

  if (!existsSync(backendExe)) {
    throw new Error(`Backend-EXE nicht gefunden: ${backendExe}`);
  }

  console.log(`Backend bereit: ${backendExe}`);
}

try {
  main();
} catch (error) {
  console.error(error.message || String(error));
  process.exit(1);
}
