const { app, BrowserWindow, dialog, Menu, Notification } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

let mainWindow = null;
let backend = null;
let backendUrl = "";
let lastMidnightFocusDate = "";
const launchedFromAutostart = process.argv.includes("--autostart");

const singleInstanceLock = app.requestSingleInstanceLock();
if (!singleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    focusMainWindow();
  });
}

function pythonCandidates() {
  if (process.platform === "win32") {
    return ["python", "py"];
  }
  return ["python3", "python"];
}

function backendCommands() {
  const commonArgs = ["--host", "127.0.0.1", "--port", "0", "--quiet"];

  if (app.isPackaged) {
    const exeName = process.platform === "win32" ? "FinanzCockpitBackend.exe" : "FinanzCockpitBackend";
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
        env: app.isPackaged
          ? { ...process.env, FINANZ_COCKPIT_APP_EXECUTABLE: process.execPath }
          : process.env,
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

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function focusMainWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

function startMidnightReminderFocus() {
  lastMidnightFocusDate = todayKey();
  setInterval(async () => {
    const currentDate = todayKey();
    if (currentDate === lastMidnightFocusDate || !backendUrl) return;
    lastMidnightFocusDate = currentDate;
    try {
      const response = await fetch(`${backendUrl}/api/overdue`);
      const payload = await response.json();
      if (payload?.ok && Array.isArray(payload.overdue) && payload.overdue.length > 0) {
        focusMainWindow();
      }
    } catch (_error) {
      // The renderer will retry normal reminder checks; focusing is best effort.
    }
  }, 60 * 1000);
}

function paymentNotificationBody(items, dueField, extraLabel) {
  const preview = items.slice(0, 3).map((item) => (
    `${item.description || "Zahlung"} (${item.amount_label || ""}) - fällig ${item[dueField] || ""}`
  ));
  const remaining = items.length - preview.length;
  if (remaining > 0) {
    preview.push(`+ ${remaining} weitere ${extraLabel}`);
  }
  return preview.join("\n");
}

function todayDateLabel() {
  const today = new Date();
  return `${String(today.getDate()).padStart(2, "0")}-${String(today.getMonth() + 1).padStart(2, "0")}-${today.getFullYear()}`;
}

function showPaymentNotification(title, body) {
  if (!Notification.isSupported()) return;
  const notification = new Notification({
    title,
    body,
    icon: path.join(__dirname, "..", "assets", "icons", "finanz-cockpit.png")
  });
  notification.on("click", focusMainWindow);
  notification.show();
}

async function notifyOpenPaymentsOnLaunch() {
  try {
    const response = await fetch(`${backendUrl}/api/state`);
    const payload = await response.json();
    const state = payload?.state;
    if (!state) return;

    const overdue = Array.isArray(state.overdue) ? state.overdue : [];
    const dueToday = (Array.isArray(state.next_due) ? state.next_due : [])
      .filter((item) => item.due === todayDateLabel());

    if (overdue.length > 0) {
      showPaymentNotification(
        `${overdue.length} überfällige Zahlung${overdue.length === 1 ? "" : "en"}`,
        paymentNotificationBody(overdue, "due_date", "überfällige Zahlungen")
      );
    }
    if (dueToday.length > 0) {
      showPaymentNotification(
        `${dueToday.length} heute fällige Zahlung${dueToday.length === 1 ? "" : "en"}`,
        paymentNotificationBody(dueToday, "due", "heute fällige Zahlungen")
      );
    }
  } catch (error) {
    console.warn("Zahlungsbenachrichtigungen konnten nicht geladen werden:", error);
  }
}

async function shouldShowWindowOnLaunch() {
  if (!launchedFromAutostart) {
    return true;
  }
  try {
    const response = await fetch(`${backendUrl}/api/state`);
    const payload = await response.json();
    const settings = payload?.state?.settings || {};
    return !settings.autostart_start_hidden;
  } catch (_error) {
    return true;
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1080,
    minHeight: 720,
    backgroundColor: "#121212",
    title: "Finanz Cockpit",
    show: false,
    autoHideMenuBar: true,
    icon: path.join(__dirname, "..", "assets", "icons", "finanz-cockpit.png"),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  mainWindow.setMenuBarVisibility(false);
  mainWindow.removeMenu();

  try {
    backendUrl = await startBackend();
    const showWindow = await shouldShowWindowOnLaunch();
    await mainWindow.loadURL(backendUrl);
    if (showWindow) {
      focusMainWindow();
    }
    await notifyOpenPaymentsOnLaunch();
    startMidnightReminderFocus();
  } catch (error) {
    dialog.showErrorBox("Finanz Cockpit", error.message || String(error));
    app.quit();
  }
}

app.whenReady().then(() => {
  app.setAppUserModelId("com.finanz.cockpit");
  Menu.setApplicationMenu(null);
  if (singleInstanceLock) {
    createWindow();
  }
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
