"""条件触发引擎 —— 移植自 Nolan 的 triggers.py（P4 · 主动性进阶）

第一性原理：提醒是「时间到 → 做」；条件触发是「条件成立 → 做」。只有两种触发源：
    周期型（interval）——「每隔 30 分钟提醒我喝水」：时间循环，无需判断；
    条件型（condition）——「如果明天下雨就提醒我带伞」：需联网评估真假。
动作两种：
    消息型（提醒我/告诉我 X）——到点把 X 说给主人听（默认，安全）；
    执行型（其它指令）——到点交给大脑执行（经注入的 executor，本模块不依赖 app）。

对外接口：
    def add_trigger(raw: str) -> dict|None   # 解析落库，返回 {ok, msg}；解析不出 None
    def list_triggers() -> dict              # 口语化列出在册任务
    def check_due(executor=None, evaluator=None) -> list[str]
    def remove_trigger(tid: str) -> dict     # 按 id 删除

存储：memory/triggers.json（JSON 数组）
"""

import json
import os
import re
import threading
import time

from ._paths import PROJECT_ROOT

_STORE = os.path.join(PROJECT_ROOT, "memory", "triggers.json")
_LOCK = threading.Lock()

# 条件型任务的默认评估间隔（分钟）：LLM 联网评估有成本，30 分钟一拍足够
_DEFAULT_CHECK_MIN = 30
# 循环条件型（每当/每次/一旦）触发后的冷却期（秒）：防条件持续为真时轰炸
_RECUR_COOLDOWN_SEC = 3600


def _read():
    try:
        with open(_STORE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write(entries):
    os.makedirs(os.path.dirname(_STORE), exist_ok=True)
    tmp = _STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _STORE)


# ========== 中文数字 → 分钟 ==========
_CN_NUM = {"一": 1, "两": 2, "半": 0.5}


def _interval_to_min(num_s, unit):
    try:
        n = _CN_NUM.get(num_s, None)
        if n is None:
            n = float(num_s)
    except ValueError:
        return None
    if unit == "秒":
        return max(n / 60.0, 0.2)  # 最小 12 秒，防零间隔死循环
    if unit == "分钟":
        return n
    if unit in ("小时", "钟头"):
        return n * 60
    if unit == "天":
        return n * 1440
    return None


# ========== 解析 ==========
_INTERVAL_RE = re.compile(
    r"每隔?\s*(\d+(?:\.\d+)?|一|两|半)\s*(个)?(秒|分钟|小时|钟头|天)")
_COND_HEAD_RE = re.compile(r"^(如果|若|要是)(.+?)[，,]?\s*(?:就|则|的话)[，,]?\s*(.+)$")
_COND_RECUR_RE = re.compile(r"^(每当|每次|一旦)(.+?)[，,]?\s*(?:就|时|的时候)[，,]?\s*(.+)$")
_ACTION_STRIP = "帮我请把那就"


def _clean_action(s):
    return s.strip(" ，。！？：:" + _ACTION_STRIP)


def _parse(raw):
    """一句自然语言 → 触发任务字典；解析不出返回 None。"""
    text = raw.strip(" ，。！？：:")
    if not text:
        return None

    # 1) 周期型：每隔 N 秒/分钟/小时/天 做 X
    m = _INTERVAL_RE.search(text)
    if m:
        minutes = _interval_to_min(m.group(1), m.group(3))
        if minutes is None:
            return None
        action = _clean_action(_INTERVAL_RE.sub("", text, count=1))
        if not action:
            return None
        return {
            "kind": "interval", "recurring": True,
            "condition": "", "action": action,
            "interval_min": minutes,
        }

    # 2) 循环条件型：每当/每次/一旦 X 就 Y
    m = _COND_RECUR_RE.match(text)
    if m:
        cond, action = m.group(2).strip(), _clean_action(m.group(3))
        if cond and action:
            return {
                "kind": "condition", "recurring": True,
                "condition": cond, "action": action,
                "interval_min": _DEFAULT_CHECK_MIN,
            }
        return None

    # 3) 单次条件型：如果/若/要是 X 就 Y
    m = _COND_HEAD_RE.match(text)
    if m:
        cond, action = m.group(2).strip(), _clean_action(m.group(3))
        if cond and action:
            return {
                "kind": "condition", "recurring": False,
                "condition": cond, "action": action,
                "interval_min": _DEFAULT_CHECK_MIN,
            }
    return None


def _is_message_action(action):
    """动作是否为消息型（到点只说不动手）。"""
    return any(action.startswith(k) for k in ("提醒我", "告诉我", "叫醒我", "叫我"))


def add_trigger(raw):
    """解析并落库一个触发任务，返回 {ok, msg}；解析不出返回 None（放行给模型）。"""
    parsed = _parse(raw)
    if parsed is None:
        return None
    now = time.time()
    entry = {
        "id": "t_%d" % int(now * 1000),
        "kind": parsed["kind"],
        "recurring": parsed["recurring"],
        "condition": parsed["condition"],
        "action": parsed["action"],
        "interval_min": parsed["interval_min"],
        "next_check": now + min(parsed["interval_min"] * 60, 300),  # 首次评估不晚于 5 分钟
        "cooldown_until": 0.0,
        "enabled": True,
        "created": now,
    }
    with _LOCK:
        entries = _read()
        entries.append(entry)
        _write(entries)

    action = entry["action"]
    if entry["kind"] == "interval":
        iv = entry["interval_min"]
        spoken = ("%g 分钟" % iv) if iv >= 1 else ("%d 秒" % round(iv * 60))
        return {"ok": True, "msg": f"好啦，每隔 {spoken} 我会{action}。已记在触发列表里。"}
    if entry["recurring"]:
        return {"ok": True, "msg": (
            f"好啦，每当「{entry['condition']}」成立时，我会{action}。"
            "我会定时核实，触发后一小时冷却，不会反复打扰你哦。")}
    return {"ok": True, "msg": (
        f"好啦，我会定时核实「{entry['condition']}」，一旦成立就{action}，只提醒一次。")}


def list_triggers():
    """口语化列出在册触发任务。返回 {ok, msg}。"""
    entries = [e for e in _read() if e.get("enabled")]
    if not entries:
        return {"ok": True, "msg": "目前还没有在册的条件触发任务哦。"}
    lines = [f"你有 {len(entries)} 个条件触发任务："]
    for i, e in enumerate(entries, 1):
        if e["kind"] == "interval":
            lines.append(f"第 {i} 个：每隔 %g 分钟，{e['action']}。" % e["interval_min"])
        else:
            tag = "每当" if e["recurring"] else "如果"
            lines.append(f"第 {i} 个：{tag}「{e['condition']}」成立，就{e['action']}。")
    return {"ok": True, "msg": "\n".join(lines)}


def remove_trigger(tid):
    """按 id 删除触发任务。返回 {ok, msg}。"""
    with _LOCK:
        entries = _read()
        keep = [e for e in entries if e.get("id") != tid]
        if len(keep) == len(entries):
            return {"ok": False, "msg": f"没找到 id 为 {tid} 的触发任务。"}
        _write(keep)
    return {"ok": True, "msg": "已删除该触发任务。"}


def _fire(entry, executor):
    """触发一个任务，返回要播报的消息文本。执行型动作经 executor 跑大脑。"""
    action = entry["action"]
    if _is_message_action(action) or executor is None:
        msg = re.sub(r"^(提醒我|告诉我|叫醒我|叫我)", "", action).strip(" ，。")
        return "条件触发：%s（源自「%s」）。" % (msg or action, _describe(entry))
    try:
        reply = executor(action)
    except Exception as exc:
        return "条件触发：%s，但执行出错了（%s）。" % (_describe(entry), exc)
    if not isinstance(reply, str) or not reply.strip():
        reply = "执行完了，没有更多要说的。"
    return "条件触发：%s。%s" % (_describe(entry), reply.strip())


def _describe(entry):
    if entry["kind"] == "interval":
        return "每隔 %g 分钟的周期任务" % entry["interval_min"]
    return "条件「%s」已成立" % entry["condition"]


def check_due(executor=None, evaluator=None):
    """评估所有到点任务，返回触发的消息列表；无触发返回 []。

    executor(cmd) -> str：执行型动作的大脑入口；
    evaluator(cond) -> bool|None：条件评估入口（联网核实），
    未注入时条件型任务顺延一拍，绝不无依据触发。
    """
    now = time.time()
    fired = []
    changed = False
    with _LOCK:
        entries = _read()
        for e in entries:
            if not e.get("enabled"):
                continue
            if now < float(e.get("next_check", 0)):
                continue
            iv_sec = float(e.get("interval_min", _DEFAULT_CHECK_MIN)) * 60

            if e["kind"] == "interval":
                fired.append(_fire(e, executor))
                e["next_check"] = now + iv_sec
                changed = True
                continue

            # 条件型：冷却期内跳过
            if now < float(e.get("cooldown_until", 0)):
                e["next_check"] = now + iv_sec
                changed = True
                continue
            verdict = evaluator(e["condition"]) if evaluator is not None else None
            if verdict is True:
                fired.append(_fire(e, executor))
                if e["recurring"]:
                    e["cooldown_until"] = now + _RECUR_COOLDOWN_SEC
                    e["next_check"] = now + _RECUR_COOLDOWN_SEC
                else:
                    e["enabled"] = False  # 单次条件：触发一次即退役
                changed = True
            else:
                # 不成立或无法评估：顺延一拍，绝不为触发而触发
                e["next_check"] = now + iv_sec
                changed = True
        if changed:
            _write(entries)
    return fired


# ========== 模块自测（不碰网络） ==========
if __name__ == "__main__":
    import tempfile
    _STORE = os.path.join(tempfile.mkdtemp(), "triggers.json")

    r = add_trigger("每隔30分钟提醒我喝水")
    assert r and "每隔" in r["msg"], r
    r = add_trigger("如果明天下雨，就提醒我带伞")
    assert r and "只提醒一次" in r["msg"], r
    r = add_trigger("每当有重大人工智能新闻，就告诉我")
    assert r and "冷却" in r["msg"], r
    assert add_trigger("今天天气怎么样") is None
    s = list_triggers()
    assert "3 个" in s["msg"], s

    entries = _read()
    for e in entries:
        e["next_check"] = 0
    _write(entries)
    msgs = check_due(evaluator=lambda c: False)
    assert any("喝水" in m for m in msgs), msgs
    assert not any("带伞" in m for m in msgs), msgs

    entries2 = _read()
    for e in entries2:
        e["next_check"] = 0
        e["cooldown_until"] = 0
    _write(entries2)
    msgs = check_due(evaluator=lambda c: True)
    assert any("带伞" in m for m in msgs), msgs
    msgs2 = check_due(evaluator=lambda c: True)
    assert not any("带伞" in m for m in msgs2), msgs2

    print("triggers 自测全过：解析/存储/周期/条件/单次退役/冷却")
