# 小暖工具层测试: 重点覆盖命令安全/文件读写/工具分发
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools


# ---------------------------------------------------------------- run_shell 安全
class TestRunShellSafety:
    def test_empty_command_rejected(self):
        r = tools.run_shell("")
        assert r["ok"] is False
        assert "为空" in r["error"]

    def test_basic_echo(self):
        r = tools.run_shell("echo hello123")
        assert r["ok"] is True
        assert r["exit_code"] == 0
        assert "hello123" in r["output"]

    def test_rm_rf_root_rejected(self):
        r = tools.run_shell("rm -rf /")
        assert r["ok"] is False
        assert "危险" in r["error"]

    def test_rm_rf_any_rejected(self):
        r = tools.run_shell("rm -rf /tmp/somewhere")
        assert r["ok"] is False

    def test_rm_split_flags_rejected(self):
        # 拆成 rm -r -f 也不放行
        r = tools.run_shell("rm -r -f /tmp/x")
        assert r["ok"] is False

    def test_shutdown_rejected(self):
        r = tools.run_shell("shutdown -h now")
        assert r["ok"] is False

    def test_write_to_etc_blocked(self):
        r = tools.run_shell("echo x > /etc/passwd")
        assert r["ok"] is False
        assert "系统" in r["error"]

    def test_write_to_etc_hosts_blocked(self):
        r = tools.run_shell("echo '1.2.3.4 abc' >> /etc/hosts")
        assert r["ok"] is False

    def test_write_windows_system_dir_blocked(self):
        r = tools.run_shell("echo x > /mnt/c/Windows/foo.txt")
        assert r["ok"] is False

    def test_command_timeout(self):
        r = tools.run_shell("sleep 30", timeout=1)
        assert r["ok"] is False
        assert "超时" in r["error"]


class TestNormalizeCmd:
    def test_rm_flags_merged(self):
        assert tools._normalize_cmd("rm -r -f /tmp/x") == "rm -rf /tmp/x"

    def test_whitespace_folded(self):
        assert tools._normalize_cmd("  ls   -la   /tmp  ") == "ls -la /tmp"


# ---------------------------------------------------------------- 文件读写
class TestReadFile:
    def test_read_missing_file(self):
        r = tools.read_file("/tmp/__no_such_file_12345__.txt")
        assert r["ok"] is False
        assert "不存在" in r["error"]

    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("小暖你好", encoding="utf-8")
        r = tools.read_file(str(f))
        assert r["ok"] is True
        assert r["content"] == "小暖你好"


class TestWriteFile:
    def test_write_to_tmp_ok(self, tmp_path):
        target = tmp_path / "sub" / "b.txt"
        r = tools.write_file(str(target), "内容abc")
        assert r["ok"] is True
        assert target.read_text(encoding="utf-8") == "内容abc"

    def test_write_to_etc_blocked(self):
        r = tools.write_file("/etc/pwned.txt", "x")
        assert r["ok"] is False
        assert "禁止" in r["error"]

    def test_write_windows_system_blocked(self):
        r = tools.write_file("/mnt/c/Windows/pwned.txt", "x")
        assert r["ok"] is False

    def test_write_outside_home_blocked(self):
        r = tools.write_file("/usr/local/pwned.txt", "x")
        assert r["ok"] is False


# ---------------------------------------------------------------- 搜索
class TestSearchFiles:
    def test_empty_pattern_rejected(self):
        r = tools.search_files("")
        assert r["ok"] is False
        assert "为空" in r["error"]


# ---------------------------------------------------------------- 工具分发
class TestExecTool:
    def test_unknown_tool(self):
        r = tools.exec_tool("no_such_tool", {})
        assert r["ok"] is False
        assert "未知工具" in r["error"]

    def test_bad_args_type(self):
        r = tools.exec_tool("run_shell", "not a dict")
        assert r["ok"] is False  # 非 dict 兜底成 {}, run_shell 缺 cmd 报参数错误

    def test_missing_required_arg(self):
        r = tools.exec_tool("run_shell", {})
        assert r["ok"] is False
        assert "参数错误" in r["error"] or "为空" in str(r)

    def test_open_app_returns_dict(self):
        r = tools.open_app("__definitely_not_installed_app_xyz__")
        assert isinstance(r, dict)
        assert "ok" in r
