const { app, BrowserWindow, Tray, Menu, nativeImage, dialog } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

const PORT = parseInt(process.env.KHUB_PORT || "8765", 10);
let mainWindow, tray, server;

function startKhub() {
  return new Promise((resolve, reject) => {
    const env = { ...process.env, KHUB_DB: process.env.KHUB_DB || "" };
    // Ollama 检测：尝试连接本地 Ollama
    http.get("http://127.0.0.1:11434/api/tags", (res) => {
      if (res.statusCode === 200) env.KHUB_LLM_URL = "http://127.0.0.1:11434";
    }).on("error", () => { /* Ollama 不可用，忽略 */ });
    server = spawn("python3", ["-u", "-m", "khub.cli", "serve", "--port", String(PORT)], {
      cwd: path.join(__dirname, ".."),
      stdio: ["ignore", "pipe", "pipe"],
      env,
    });
    server.stdout.on("data", (d) => { if (d.toString().includes(":" + String(PORT))) resolve(); });
    server.stderr.on("data", (d) => { if (d.toString().includes(":" + String(PORT))) resolve(); });
    setTimeout(() => reject(new Error("后端启动超时")), 20000);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200, height: 800, minWidth: 800, minHeight: 600,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
    icon: path.join(__dirname, "icons", "khub.png"),
    title: "kHUB 个人知识中枢",
  });
  mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
  mainWindow.on("close", (e) => { if (!app.isQuitting) { e.preventDefault(); mainWindow.hide(); } });
}

function createTray() {
  const iconPath = path.join(__dirname, "icons", "khub.png");
  const icon = nativeImage.createFromPath(iconPath);
  tray = new Tray(icon);
  tray.setToolTip("kHUB 个人知识中枢");
  const ctxMenu = Menu.buildFromTemplate([
    { label: "显示窗口", click: () => mainWindow.show() },
    { type: "separator" },
    { label: "退出", click: () => { app.isQuitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(ctxMenu);
  tray.on("double-click", () => mainWindow.show());
}

function createMenu() {
  const template = [
    { label: "文件", submenu: [
      { label: "打开本地库", click: async () => {
        const r = await dialog.showOpenDialog({ properties: ["openDirectory"] });
        if (!r.canceled) mainWindow.loadURL(`http://127.0.0.1:${PORT}/`);
      }},
      { type: "separator" },
      { role: "quit", label: "退出" },
    ]},
    { label: "帮助", submenu: [
      { label: "关于 kHUB", click: () => {
        dialog.showMessageBox(mainWindow, {
          type: "info", title: "关于 kHUB",
          message: "kHUB 个人知识中枢", detail: `版本 0.2.11\n端口 ${PORT}`,
        });
      }},
    ]},
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(async () => {
  try {
    await startKhub();
    createMenu();
    createWindow();
    createTray();
  } catch (e) {
    dialog.showErrorBox("启动失败", e.message);
    app.quit();
  }
});

app.on("before-quit", () => { if (server) server.kill("SIGTERM"); });
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
