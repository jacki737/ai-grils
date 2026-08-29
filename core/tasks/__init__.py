"""后台任务执行: 工具循环、异步任务队列、状态管理"""
import asyncio
import json
import threading
import time
import uuid
from pathlib import Path

from core.brain import call_llm
from core.memory import load_role_history, save_role_history
from core.persona import resolve_persona
from tools import TOOLS_SCHEMA, exec_tool
from core.brain import _has_image
import re


def clean_reply(text):
    """清洗 LLM 回复: 去 markdown 符号, 保留纯口语文本"""
    if not text:
        return text
    t = text
    t = re.sub(r'```[\s\S]*?```', lambda m: re.sub(r'[\r\n]+', '。', m.group(0)), t)
    t = re.sub(r'`([^`]*)`', r'\1', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'\*([^*\n]+?)\*', r'\1', t)
    t = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'^#{1,6}\s*', '', t, flags=re.M)
    t = re.sub(r'^>\s?', '', t, flags=re.M)
    t = re.sub(r'^\s*[-*+]\s+', '。', t, flags=re.M)
    t = t.replace('**', '')
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


# 后台任务表: task_id -> {"status": "running"/"done"/"error", "reply", "tool_used"}
_bg_tasks = {}
_bg_task_lock = threading.Lock()
_MAX_BG_TASKS = 100
_MAX_TASK_AGE_HOURS = 24

# SSE 事件队列: task_id -> asyncio.Queue
_bg_events = {}


def _cleanup_old_tasks():
    """清理完成超过 24h 的任务, 防止内存泄漏"""
    now = time.time()
    stale = [
        tid for tid, t in _bg_tasks.items()
        if t.get("status") != "running" and (now - t.get("_finished_at", 0)) > _MAX_TASK_AGE_HOURS * 3600
    ]
    for tid in stale:
        _bg_tasks.pop(tid, None)
        _bg_events.pop(tid, None)


def get_task_status(task_id):
    return _bg_tasks.get(task_id)


def _emit(task_id: str, event: dict):
    """向 SSE 队列推送事件 (线程安全, 供后台线程调用)"""
    q = _bg_events.get(task_id)
    if q:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _ensure_event_queue(task_id: str) -> asyncio.Queue:
    """获取或创建任务的事件队列"""
    if task_id not in _bg_events:
        _bg_events[task_id] = asyncio.Queue(maxsize=200)
    return _bg_events[task_id]


def get_event_queue(task_id: str) -> asyncio.Queue | None:
    """前端 SSE 用: 获取已存在的队列"""
    return _bg_events.get(task_id)


def _run_tool_loop(task_id, role, messages, first_msg, user_text):
    """后台线程: 从第一轮工具调用开始, 把整个工具循环跑完"""
    q = _ensure_event_queue(task_id)
    try:
        _bg_tasks[task_id] = {"status": "running", "reply": "", "tool_used": True, "_finished_at": 0}
        _emit(task_id, {"type": "start", "msg": "开始执行..."})

        messages.append({
            "role": "assistant",
            "content": first_msg.get("content") or "",
            "tool_calls": first_msg.get("tool_calls") or [],
        })
        reply = "（我一下子没想好怎么回你...）"
        current = first_msg
        for round_idx in range(8):
            calls = current.get("tool_calls") or []
            if not calls:
                reply = clean_reply(current.get("content") or "") or "（我一下子没想好怎么回你...）"
                break
            _emit(task_id, {"type": "progress", "round": round_idx + 1, "calls": len(calls)})
            for tc in calls:
                fname = tc.get("function", {}).get("name", "")
                try:
                    fargs = json.loads(tc.get("function", {}).get("arguments") or "{}")
                except Exception:
                    fargs = {}
                _emit(task_id, {"type": "tool_start", "name": fname, "args": fargs})
                print(f"[后台任务] {task_id[:8]} 工具调用: {fname} {json.dumps(fargs, ensure_ascii=False)}")
                result = exec_tool(fname, fargs)
                _emit(task_id, {"type": "tool_done", "name": fname, "ok": isinstance(result, dict) and result.get("ok")})
                content = json.dumps(result, ensure_ascii=False)[:4000]
                if isinstance(result, dict) and result.get("image_base64"):
                    import datetime as _dt
                    _now = _dt.datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
                    content = [
                        {"type": "text", "text": (
                            f"以下是刚截取的屏幕截图(截图时间: {_now})。"
                            "请只描述这张图片里真实可见的内容, 严禁编造图片里不存在的时间/文字/细节; "
                            "看不清的就说看不清。")},
                        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + result["image_base64"]}},
                    ]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": content,
                })
            current = call_llm(messages, tools=TOOLS_SCHEMA)
            if current.get("tool_calls"):
                messages.append({
                    "role": "assistant",
                    "content": current.get("content") or "",
                    "tool_calls": current.get("tool_calls"),
                })
        else:
            reply = "（这个任务执行比较费劲，我先把能做的做了，具体结果可以再问我。）"

        history = load_role_history(role)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
        save_role_history(role, history)

    except Exception as e:
        print(f"[后台任务] {task_id[:8]} 异常: {e}")
        reply = f"（后台执行出错：{e}）"
        _emit(task_id, {"type": "error", "msg": str(e)})
    finally:
        _bg_tasks[task_id] = {"status": "done", "reply": reply, "tool_used": True, "_finished_at": time.time()}
        _emit(task_id, {"type": "done", "reply": reply})


def _extract_json(text):
    """从 LLM 回复中提取第一个 JSON 对象(容错 markdown 代码块/前后杂文/思考内容)"""
    if not text:
        return None
    import re
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _plan_and_execute_bg(task_id, role, user_text):
    """P1 分层规划: 拆步 -> 串行执行 -> 汇总; 规划失败自动降级为普通工具循环"""
    q = _ensure_event_queue(task_id)
    try:
        persona = resolve_persona(role)
        system = persona["system"] + "\n你是规划执行助手。把用户的大目标拆成 3-5 个原子步骤, 每步只做一件事, 按顺序执行。只输出 JSON(不要任何其他文字、不要markdown代码块): {\"steps\": [{\"desc\": \"步骤描述\", \"tool\": \"工具名或null\", \"args\": {...}}]}"
        plan_msg = call_llm([{"role": "system", "content": system}, {"role": "user", "content": user_text}])
        plan = _extract_json(plan_msg.get("content") or "")
        steps = (plan or {}).get("steps") or []
        if not steps:
            print(f"[规划] {task_id[:8]} 解析失败, 降级为普通工具循环")
            messages = [{"role": "system", "content": persona["system"]}]
            first = call_llm(messages + [{"role": "user", "content": user_text}], tools=TOOLS_SCHEMA)
            if first.get("tool_calls"):
                _run_tool_loop(task_id, role, messages, first, user_text)
                return
            reply = clean_reply(first.get("content") or "") or "（没听懂要做什么…）"
            history = load_role_history(role)
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply})
            save_role_history(role, history)
            _bg_tasks[task_id] = {"status": "done", "reply": reply, "tool_used": False, "_finished_at": time.time()}
            _emit(task_id, {"type": "done", "reply": reply})
            return
        messages = [{"role": "system", "content": "你是执行助手。按计划逐步调用工具, 每步完成后汇报结果。"}]
        results = []
        for i, step in enumerate(steps):
            _emit(task_id, {"type": "plan_step", "index": i + 1, "total": len(steps), "desc": step.get("desc")})
            fname = step.get("tool")
            fargs = step.get("args", {})
            if fname:
                result = exec_tool(fname, fargs)
                results.append(result)
                _emit(task_id, {"type": "tool_done", "name": fname, "ok": isinstance(result, dict) and result.get("ok")})
                messages.append({"role": "user", "content": f"步骤 {i+1}/{len(steps)} ({step.get('desc')}) 结果: {json.dumps(result, ensure_ascii=False)[:1500]}"})
            else:
                messages.append({"role": "user", "content": f"步骤 {i+1}/{len(steps)} 无需工具: {step.get('desc')}"})
        summary_msg = call_llm([{"role": "system", "content": "把执行结果汇总成一句自然口语回复给用户, 不要用markdown。"}, {"role": "user", "content": f"计划已完成, 各步结果: {json.dumps(results, ensure_ascii=False)[:3000]}"}])
        reply = clean_reply((summary_msg.get("content") or "").strip()) or "做完了～"
    except Exception as e:
        print(f"[规划] {task_id[:8]} 异常: {e}")
        reply = f"（执行出错了：{e}）"
        _emit(task_id, {"type": "error", "msg": str(e)})
    _bg_tasks[task_id] = {"status": "done", "reply": reply, "tool_used": True, "_finished_at": time.time()}
    _emit(task_id, {"type": "done", "reply": reply})


def start_bg_task(role, messages, first_msg, user_text):
    """启动后台任务, 返回 task_id"""
    _cleanup_old_tasks()
    if len(_bg_tasks) > _MAX_BG_TASKS:
        for k in list(_bg_tasks)[:20]:
            if _bg_tasks[k].get("status") != "running":
                _bg_tasks.pop(k, None)
    task_id = uuid.uuid4().hex
    _ensure_event_queue(task_id)  # 预创建队列
    threading.Thread(target=_run_tool_loop, args=(task_id, role, messages, first_msg, user_text), daemon=True).start()
    return task_id