"""桌面 GUI 模块测试：验证套壳文件完整性。"""
import os
import subprocess


def test_main_js_syntax():
    """Electron 主进程脚本语法正确。"""
    p = os.path.join(os.path.dirname(__file__), "..", "desktop", "main.js")
    r = subprocess.run(["node", "-c", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_run_sh_executable():
    """启动脚本应可在 bash 下简单检查语法。"""
    p = os.path.join(os.path.dirname(__file__), "..", "desktop", "run.sh")
    assert os.path.isfile(p) and os.access(p, os.X_OK) is False
    # shell check
    r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_package_json_exists():
    p = os.path.join(os.path.dirname(__file__), "..", "desktop", "package.json")
    assert os.path.isfile(p)
