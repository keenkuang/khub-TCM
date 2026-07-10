import subprocess
import sys
import pytest
pytestmark = pytest.mark.smoke



def _run(*args):
    """运行 khub CLI 子命令，返回 (returncode, stdout, stderr)。"""
    r = subprocess.run([sys.executable, "-m", "khub.cli"] + list(args),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


def test_cli_help():
    """khub --help 应成功。"""
    rc, out, _ = _run("--help")
    assert rc == 0
    assert "usage:" in out.lower()


def test_cli_serve_help():
    """khub serve --help 应显示端口选项。"""
    rc, out, _ = _run("serve", "--help")
    assert rc == 0
    assert "--port" in out


def test_cli_add_help():
    """khub add --help 应显示 --move。"""
    rc, out, _ = _run("add", "--help")
    assert rc == 0
    assert "--move" in out


def test_cli_ima_sync_help():
    """khub ima-sync --help 应显示 direction。"""
    rc, out, _ = _run("ima-sync", "--help")
    assert rc == 0
    assert "--direction" in out or "--kb-id" in out


def test_cli_no_args_prints_help():
    """khub（无参数）应打印帮助。"""
    rc, out, _ = _run()
    assert rc != 0 or "usage:" in out.lower()


def test_cli_bad_command_fails():
    """khub nonexistent 应报错。"""
    rc, _, err = _run("nonexistent")
    assert rc != 0


def test_color_output():
    from khub.color import C
    assert C.green("ok") != "ok"
    assert C.ok("done").startswith("\033[92m[OK]")


def test_completion_subcommand():
    from khub.cli import build_parser
    parser = build_parser()
    for action in parser._actions:
        if hasattr(action, 'choices') and action.choices:
            assert "completion" in action.choices
