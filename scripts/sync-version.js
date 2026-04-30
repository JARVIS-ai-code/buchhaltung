#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const versionFile = path.join(root, "version.json");
const packageFile = path.join(root, "package.json");
const lockFile = path.join(root, "package-lock.json");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2) + "\n", "utf8");
}

function main() {
  const versionPayload = readJson(versionFile);
  const targetVersion = String(versionPayload.version || "").trim();
  if (!targetVersion) {
    throw new Error("version.json enthält keine gültige version.");
  }

  let changed = false;
  const packagePayload = readJson(packageFile);
  if (String(packagePayload.version || "").trim() !== targetVersion) {
    packagePayload.version = targetVersion;
    writeJson(packageFile, packagePayload);
    changed = true;
  }

  if (fs.existsSync(lockFile)) {
    const lockPayload = readJson(lockFile);
    if (String(lockPayload.version || "").trim() !== targetVersion) {
      lockPayload.version = targetVersion;
      changed = true;
    }
    if (lockPayload.packages && lockPayload.packages[""] && String(lockPayload.packages[""].version || "").trim() !== targetVersion) {
      lockPayload.packages[""].version = targetVersion;
      changed = true;
    }
    if (changed) {
      writeJson(lockFile, lockPayload);
    }
  }

  if (changed) {
    console.log(`Version synchronisiert: ${targetVersion}`);
  } else {
    console.log(`Version bereits synchron: ${targetVersion}`);
  }
}

try {
  main();
} catch (error) {
  console.error(error.message || String(error));
  process.exit(1);
}
