"""内置定时调度器模块，支持按时间间隔周期性执行 khub CLI 命令。"""

import os
import subprocess
import threading
import time

_TASK_TIMEOUT = 300  # 每个任务默认超时 300 秒


class Scheduler:
    """定时调度器，管理多个周期性任务。"""

    def __init__(self):
        self._tasks = []
        self._running = False

    def add_task(self, name: str, interval: float, callable):
        """添加一个定时任务。

        Args:
            name: 字符串标识。
            interval: 执行间隔（秒）。
            callable: 无参可调用对象。
        """
        self._tasks.append({
            "name": name,
            "interval": interval,
            "callable": callable,
            "next_run": 0.0,
        })

    def run(self, blocking: bool = True):
        """启动调度器。

        Args:
            blocking: 若为 True，在当前线程阻塞运行；否则在后台守护线程运行。
        """
        self._running = True
        if blocking:
            self._loop()
        else:
            t = threading.Thread(target=self._loop, daemon=True)
            t.start()

    def stop(self):
        """停止调度器。"""
        self._running = False

    def _loop(self):
        """调度主循环。"""
        while self._running:
            now = time.monotonic()
            for task in self._tasks:
                if now >= task["next_run"]:
                    try:
                        task["callable"]()
                    except Exception as e:
                        print(
                            f"[scheduler] WARNING: task '{task['name']}' "
                            f"raised {type(e).__name__}: {e}"
                        )
                    task["next_run"] = now + task["interval"]
            time.sleep(1)


def _run_cmd(cmd: str):
    """执行 shell 命令。"""
    try:
        subprocess.run(
            cmd,
            shell=True,
            timeout=_TASK_TIMEOUT,
            capture_output=True,
        )
    except Exception as e:
        print(f"[scheduler] WARNING: command failed '{cmd}': {e}")


def read_tasks(path: str) -> list[dict]:
    """从 YAML 文件读取任务列表。

    如果 PyYAML 未安装、文件不存在或格式错误，返回空列表。

    Args:
        path: YAML 文件路径。

    Returns:
        list[dict]: 任务字典列表。
    """
    try:
        import yaml
    except ImportError:
        print("[scheduler] WARNING: PyYAML not installed, cannot read tasks")
        return []

    if not os.path.isfile(path):
        print(f"[scheduler] ERROR: file not found: {path}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            return []
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            print(f"[scheduler] ERROR: 'tasks' is not a list in {path}")
            return []
        return tasks
    except Exception as e:
        print(f"[scheduler] ERROR: failed to read tasks from {path}: {e}")
        return []


def run_tasks(store, tasks: list[dict], blocking: bool = True):
    """创建调度器并运行一组任务。

    Args:
        store: 预留参数（当前未使用）。
        tasks: 任务字典列表，每项应包含 name / command / interval 字段。
        blocking: 是否阻塞运行。
    """
    scheduler = Scheduler()
    for task in tasks:
        name = task.get("name", "unknown")
        interval = task.get("interval", 60)
        command = task.get("command", "")
        if not command:
            continue
        scheduler.add_task(
            name=name,
            interval=interval,
            callable=lambda c=command: _run_cmd(c),
        )
    scheduler.run(blocking=blocking)
    return scheduler
