const { app, BrowserWindow, dialog, Menu } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

let mainWindow = null;
let backend = null;

function pythonCandidates() {
  if (process.platform === "win32") {
    return ["python", "py"];
  }
  return ["python3", "python"];
}

function backendCommands() {
  const commonArgs = ["--host", "127.0.0.1", "--port", "0", "--quiet"];

  if (app.isPackaged) {
    const exeName = process.platform === "win32" ? "JarvisBuchhaltungBackend.exe" : "JarvisBuchhaltungBackend";
    const backendExe = path.join(process.resourcesPath, "backend", exeName);
    if (fs.existsSync(backendExe)) {
      return [
        {
          command: backendExe,
          args: commonArgs,
          cwd: path.dirname(backendExe),
          label: backendExe
        }
      ];
    }

    const scriptPath = path.join(process.resourcesPath, "backend", "app_backend.py");
    if (fs.existsSync(scriptPath)) {
      return pythonCandidates().map((candidate) => ({
        command: candidate,
        args: [scriptPath, ...commonArgs],
        cwd: process.resourcesPath,
        label: `${candidate} ${scriptPath}`
      }));
    }

    throw new Error("Backend-Komponente fehlt im Installationspaket.");
  }

  const root = path.resolve(__dirname, "..");
  const scriptPath = path.join(root, "app_backend.py");
  return pythonCandidates().map((candidate) => ({
    command: candidate,
    args: [scriptPath, ...commonArgs],
    cwd: root,
    label: `${candidate} ${scriptPath}`
  }));
}

function startBackend() {
  return new Promise((resolve, reject) => {
    let commands = [];
    try {
      commands = backendCommands();
    } catch (error) {
      reject(error);
      return;
    }

    let index = 0;

    const tryNext = () => {
      if (index >= commands.length) {
        reject(new Error("Backend konnte nicht gestartet werden."));
        return;
      }

      const launch = commands[index++];
      backend = spawn(launch.command, launch.args, {
        cwd: launch.cwd,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true
      });

      let ready = false;
      let stdoutBuffer = "";
      const startupTimer = setTimeout(() => {
        if (!ready) {
          backend.kill();
          reject(new Error("Backend-Start hat zu lange gedauert."));
        }
      }, 12000);

      backend.on("error", () => {
        clearTimeout(startupTimer);
        tryNext();
      });

      backend.stdout.on("data", (chunk) => {
        stdoutBuffer += chunk.toString("utf8");
        const lines = stdoutBuffer.split(/\r?\n/);
        stdoutBuffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const message = JSON.parse(line);
            if (message.ready && message.port) {
              ready = true;
              clearTimeout(startupTimer);
              resolve(`http://${message.host || "127.0.0.1"}:${message.port}`);
              return;
            }
          } catch (_err) {
            // Ignore non-JSON backend output during development.
          }
        }
      });

      backend.stderr.on("data", (chunk) => {
        console.error(chunk.toString("utf8"));
      });

      backend.on("exit", (code) => {
        if (!ready) {
          clearTimeout(startupTimer);
          reject(new Error(`Backend wurde beendet (Code ${code}) mit Startbefehl: ${launch.label}`));
          return;
        }
        if (code === 77) {
          app.relaunch();
          app.exit(0);
        }
      });
    };

    tryNext();
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1080,
    minHeight: 720,
    backgroundColor: "#121212",
    title: "JARVIS Buchhaltungssystem",
    autoHideMenuBar: true,
    icon: path.join(__dirname, "..", "assets", "icons", "jarvis-buchhaltung.png"),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.removeMenu();

  try {
    const backendUrl = await startBackend();
    await mainWindow.loadURL(backendUrl);
  } catch (error) {
    dialog.showErrorBox("JARVIS Buchhaltung", error.message || String(error));
    app.quit();
  }
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on("before-quit", () => {
  if (backend && !backend.killed) {
    backend.kill();
  }
});
