"""测试 khub.scheduler 模块。"""

import os
import tempfile
import time

from khub.scheduler import Scheduler, read_tasks
import pytest
pytestmark = pytest.mark.smoke



def test_background_mode_multiple_triggers():
    """后台模式下，任务应在指定间隔内多次触发。"""
    calls = []

    scheduler = Scheduler()
    scheduler.add_task("test", 0.1, lambda: calls.append(1))
    scheduler.run(blocking=False)

    time.sleep(2.5)
    scheduler.stop()

    # 2.5s 可覆盖调度器 sleep(1) 的 2 个完整周期，应至少触发 2 次
    assert len(calls) >= 2, f"期望 >= 2 次调用，实际 {len(calls)}"


def test_exception_does_not_break_scheduler():
    """一个任务抛异常不应阻止其他任务继续执行。"""
    results = []

    def failing():
        raise RuntimeError("boom")

    def normal():
        results.append("ok")

    scheduler = Scheduler()
    scheduler.add_task("failing", 0.1, failing)
    scheduler.add_task("normal", 0.1, normal)
    scheduler.run(blocking=False)

    time.sleep(2.5)
    scheduler.stop()

    # 正常任务应至少触发 2 次
    assert len(results) >= 2, f"期望 >= 2 次正常调用，实际 {len(results)}"


def test_read_tasks_valid_yaml():
    """从有效的 YAML 文件读取任务列表。"""
    content = (
        "tasks:\n"
        '  - name: sync-quip\n'
        '    command: "khub quip-sync --token env:QUIP_TOKEN"\n'
        "    interval: 3600\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write(content)
        tmp_path = f.name

    try:
        tasks = read_tasks(tmp_path)
        assert len(tasks) == 1
        assert tasks[0]["name"] == "sync-quip"
        assert tasks[0]["interval"] == 3600
    finally:
        os.unlink(tmp_path)


def test_read_tasks_file_not_found():
    """文件不存在时应返回空列表。"""
    tasks = read_tasks("/tmp/nonexistent_scheduler_test.yaml")
    assert tasks == []


def test_read_tasks_invalid_format():
    """格式错误的 YAML 应返回空列表。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        f.write("not: valid: yaml: [\n")
        tmp_path = f.name

    try:
        tasks = read_tasks(tmp_path)
        assert tasks == []
    finally:
        os.unlink(tmp_path)
