#!/usr/bin/env node
const { spawn } = require("child_process");
const electron = require("electron");
const path = require("path");

const root = path.resolve(__dirname, "..");
const env = { ...process.env };
delete env.ELECTRON_RUN_AS_NODE;

const child = spawn(electron, [root, ...process.argv.slice(2)], {
  cwd: root,
  env,
  stdio: "inherit",
  windowsHide: false
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code || 0);
});
