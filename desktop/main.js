const { app, BrowserWindow, Tray, Menu, nativeImage } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

const PORT = 8765; // 固定端口，与 khub desktop 一致
let mainWindow = null;
let tray = null;
let server = null;

function startKhub() {
  return new Promise((resolve, reject) => {
    const khubPath = path.join(__dirname, "..", "khub", "cli.py");
    server = spawn("python3", ["-u", "-m", "khub.cli", "serve", "--port", String(PORT)], {
      cwd: path.join(__dirname, ".."),
      stdio: ["ignore", "pipe", "pipe"],
      env: { ...process.env },
    });

    server.stdout.once("data", () => resolve());
    server.stderr.once("data", (d) => {
      const msg = d.toString();
      if (msg.includes("khub API on")) resolve();
      else reject(new Error(msg));
    });
    server.on("error", reject);
    server.on("exit", (code) => {
      if (code !== 0) reject(new Error(`khub exited with ${code}`));
    });

    // 超时 15s
    setTimeout(() => reject(new Error("khub start timeout")), 15000);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    title: "kHUB",
    webPreferences: { nodeIntegration: false, contextIsolation: true },
    icon: nativeImage.createEmpty(),
  });
  mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
  mainWindow.on("closed", () => (mainWindow = null));
  mainWindow.on("close", (e) => {
    // 最小化到托盘而非退出
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
}

function createTray() {
  // 用空图标作为 fallback（用户可替换为 khub 图标）
  tray = new Tray(nativeImage.createEmpty());
  tray.setToolTip("kHUB · 个人知识中枢");
  const ctx = Menu.buildFromTemplate([
    { label: "显示窗口", click: () => mainWindow && mainWindow.show() },
    { type: "separator" },
    { label: "退出", click: () => { app.isQuitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(ctx);
  tray.on("double-click", () => mainWindow && mainWindow.show());
}

app.whenReady().then(async () => {
  try {
    await startKhub();
    createWindow();
    createTray();
  } catch (e) {
    console.error("启动失败:", e.message);
    app.quit();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (server) server.kill("SIGTERM");
});

app.on("activate", () => {
  if (mainWindow === null) createWindow();
});
