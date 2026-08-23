"""记忆与历史: JSON 文件存储 + 自动摘要压缩"""
# -*- coding: utf-8 -*-
import json
from pathlib import Path

from core.brain import call_llm
from core.persona import PERSONAS_DB


HISTORY_DIR = Path(__file__).parent.parent.parent / "histories"


def _save_history_file(role, messages):
    HISTORY_DIR.mkdir(exist_ok=True)
    (HISTORY_DIR / f"{role}.json").write_text(
        json.dumps(messages, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def load_role_history(role, limit=30):
    f = HISTORY_DIR / f"{role}.json"
    if f.exists():
        try:
            msgs = json.loads(f.read_text(encoding="utf-8"))
            return msgs[-limit:]
        except Exception:
            pass
    return []


def save_role_history(role, messages):
    """保存角色对话历史(JSON 文件, 保留最近 500 条)"""
    _save_history_file(role, messages[-500:])


def _load_full_history(role):
    f = HISTORY_DIR / f"{role}.json"
    if f.exists():
        try:
            msgs = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(msgs, list) and msgs:
                return msgs
        except Exception:
            pass
    return []


def _history_summary(role, full):
    """超长历史 -> 用聊天模型压缩成一段记忆摘要(缓存, 每隔约20条新消息才重新生成一次)"""
    if len(full) <= 60:
        return ""
    mem_file = Path(__file__).parent.parent.parent / "histories" / f"{role}_mem.json"
    old = full[:-20]
    old_text = "\n".join(
        (str(m.get("role", "?") if isinstance(m, dict) else "?") + ": " + str(m.get("content", "")))
        for m in old
        if isinstance(m, dict) and isinstance(m.get("content"), str) and m.get("content").strip()
    )
    if len(old_text) > 12000:
        old_text = old_text[-12000:]
    try:
        if mem_file.exists():
            data = json.loads(mem_file.read_text(encoding="utf-8"))
            if data.get("summary") and len(full) <= (data.get("summarized") or 0) + 20:
                return data["summary"]
    except Exception:
        pass
    summary = ""
    try:
        msg = call_llm([
            {"role": "system", "content": "你是记忆压缩器。把下面用户和AI的历史聊天记录压缩成一段300字以内的第三人称记忆摘要, 保留用户的重要信息: 名字/称呼、喜好、讨厌的事、性格、做过的重要事情、约定承诺、未完成的任务、用户设备软件情况。只输出摘要本身, 不要任何前缀。"},
            {"role": "user", "content": old_text},
        ])
        summary = (msg.get("content") or "").strip()
    except Exception:
        summary = ""
    if summary:
        try:
            mem_file.write_text(
                json.dumps({"summarized": len(full), "summary": summary}, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass
    return summary


def get_memory(role):
    full = _load_full_history(role)
    return _history_summary(role, full)