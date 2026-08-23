# app.py 测试: markdown 清洗 / 工具调用解析 / 历史读写 / 人设 / chat 流程
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app
import tools


# ---------------------------------------------------------------- clean_reply
class TestCleanReply:
    def test_bold_removed(self):
        assert app.clean_reply("**加粗**文字") == "加粗文字"

    def test_inline_code(self):
        assert app.clean_reply("用 `ls` 命令") == "用 ls 命令"

    def test_link_to_text(self):
        assert app.clean_reply("[项目](https://github.com/x)") == "项目"

    def test_heading(self):
        assert app.clean_reply("# 标题") == "标题"

    def test_list_item(self):
        assert app.clean_reply("- 项目") == "。项目"

    def test_quote(self):
        assert app.clean_reply("> 引用") == "引用"

    def test_none_and_empty(self):
        assert app.clean_reply(None) is None
        assert app.clean_reply("") == ""

    def test_code_block_newlines(self):
        out = app.clean_reply("看这个：\n```\nprint(1)\nprint(2)\n```\n结束了")
        assert "\n" not in out.split("看这个")[1].split("结束了")[0] or "。" in out


# ---------------------------------------------------------------- 工具调用解析
class TestExtractTextToolcalls:
    def test_parse_valid(self):
        content = '<tool_call>{"name":"run_shell","arguments":{"cmd":"ls"}}</tool_call>'
        calls = app._extract_text_toolcalls(content)
        assert len(calls) == 1
        c = calls[0]
        assert c["type"] == "function"
        assert c["function"]["name"] == "run_shell"
        assert json.loads(c["function"]["arguments"]) == {"cmd": "ls"}
        assert c["id"].startswith("call_")

    def test_invalid_json_ignored(self):
        assert app._extract_text_toolcalls("<tool_call>not json</tool_call>") == []

    def test_no_match(self):
        assert app._extract_text_toolcalls("随便说说而已") == []

    def test_none(self):
        assert app._extract_text_toolcalls(None) == []

    def test_missing_name_ignored(self):
        content = '<tool_call>{"arguments":{}}</tool_call>'
        assert app._extract_text_toolcalls(content) == []


# ---------------------------------------------------------------- 历史读写
class TestHistory:
    def test_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "HISTORY_DIR", tmp_path)
        msgs = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好呀"}]
        app.save_role_history("plankton", msgs)
        assert app.load_role_history("plankton") == msgs

    def test_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "HISTORY_DIR", tmp_path)
        long = [{"role": "user", "content": f"消息{i}"} for i in range(100)]
        app.save_role_history("plankton", long)
        assert len(app.load_role_history("plankton")) == 30
        assert len(app.load_role_history("plankton", limit=5)) == 5

    def test_missing_role(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, "HISTORY_DIR", tmp_path)
        assert app.load_role_history("__no_such_role__") == []


# ---------------------------------------------------------------- 人设
class TestResolvePersona:
    def test_existing_role(self):
        p = app.resolve_persona("plankton")
        assert "system" in p
        assert "name" in p

    def test_unknown_role_falls_back(self):
        p = app.resolve_persona("__no_such_role__")
        assert "system" in p
        assert p["name"] == app.PERSONAS[app.DEFAULT_ROLE]["name"]

    def test_none_falls_back(self):
        p = app.resolve_persona(None)
        assert "system" in p


# ---------------------------------------------------------------- key 选择
class TestGetEffectiveKey:
    def test_config_priority(self, monkeypatch):
        monkeypatch.setattr(app, "load_config", lambda: {"tool_key": "fromcfg"})
        assert app.get_effective_key("TOOL_KEY", "tool_key", "current") == "fromcfg"

    def test_fallback_to_current(self, monkeypatch):
        monkeypatch.setattr(app, "load_config", lambda: {})
        assert app.get_effective_key("TOOL_KEY", "tool_key", "current") == "current"

    def test_blank_config_value_ignored(self, monkeypatch):
        monkeypatch.setattr(app, "load_config", lambda: {"tool_key": "   "})
        assert app.get_effective_key("TOOL_KEY", "tool_key", "current") == "current"


# ---------------------------------------------------------------- chat 流程
@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(app, "_load_full_history", lambda role: [])
    app._bg_tasks.clear()
    yield
    app._bg_tasks.clear()


class TestChat:
    def test_empty_message_400(self, isolated):
        resp = app.chat({"message": "   "})
        assert resp.status_code == 400

    def test_normal_chat_no_tools(self, isolated, monkeypatch):
        calls = []

        def fake_call(messages, tools=None):
            calls.append(tools)
            return {"content": "**你好呀**", "tool_calls": []}

        monkeypatch.setattr(app, "call_deepseek", fake_call)
        resp = app.chat({"message": "你好"})
        assert resp["tool_used"] is False
        assert resp["reply"] == "你好呀"
        assert calls == [None]  # 闲聊不传工具

    def test_tool_trigger_passes_tools(self, isolated, monkeypatch):
        seen = {}

        def fake_call(messages, tools=None):
            seen["tools"] = tools
            return {"content": "结果: 完成", "tool_calls": []}

        monkeypatch.setattr(app, "call_deepseek", fake_call)
        resp = app.chat({"message": "帮我打开微信"})
        assert resp["tool_used"] is False
        assert seen["tools"] is not None

    def test_tool_trigger_async_flow(self, isolated, monkeypatch):
        # 第一轮: 返回工具调用; 第二轮: 返回最终文本
        seq = iter([
            {"content": "", "tool_calls": [{
                "id": "call_test",
                "type": "function",
                "function": {"name": "run_shell", "arguments": '{"cmd":"echo ok"}'},
            }]},
            {"content": "运行结果: 成功", "tool_calls": []},
        ])

        def fake_call(messages, tools=None):
            return next(seq)

        monkeypatch.setattr(app, "call_deepseek", fake_call)
        monkeypatch.setattr(tools, "exec_tool",
                            lambda name, args: {"ok": True, "output": "ok", "exit_code": 0})
        resp = app.chat({"message": "帮我运行一条命令"})
        assert resp["tool_used"] is True
        assert resp["async"] is True
        assert resp["task_id"]

        # 等待后台线程跑完
        deadline = time.time() + 10
        while time.time() < deadline:
            t = app._bg_tasks.get(resp["task_id"])
            if t and t["status"] == "done":
                break
            time.sleep(0.05)
        assert app._bg_tasks[resp["task_id"]]["status"] == "done"
        assert app._bg_tasks[resp["task_id"]]["reply"] == "运行结果: 成功"