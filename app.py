#!/usr/bin/env python3
"""AI 女友 Web 服务 - FastAPI 后端 (拆包后入口)"""
# -*- coding: utf-8 -*-

import json
import re
import time
import urllib.request
from pathlib import Path

from logsetup import setup_logging
setup_logging()

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.persona import resolve_persona, load_personas, get_role_voice, PERSONAS
from core.stt import transcribe
from core.tts import synthesize
from core.speak_filter import speak_filter
from core.brain import call_llm
from core.memory import load_role_history, save_role_history, get_memory
from core.tasks import start_bg_task, get_task_status, get_event_queue
from core.proactive import proactive_allowed
from tools import TOOLS_SCHEMA, exec_tool

app = FastAPI()
print("[APP VERSION] v3-20260822 tokens-from-config")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

@app.get("/")
def root():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).parent / "static" / "index.html")

DEFAULT_ROLE = "jarvis"

# ===== URL/模型名硬编码(在 core/brain/__init__.py 里) =====

TOOL_TRIGGER_RE = re.compile(
    r"打开|关闭|搜索|搜一下|查|天气|新闻|音乐|视频|下载|爬|抓取|运行|执行|启动|播放|翻译|"
    r"计算|日历|邮件|写代码|代码|屏幕|截图|拍照|备忘|提醒|闹钟|导航|地图|知乎|微博|"
    r"哔哩|b站|bilibili|淘宝|京东|豆瓣|股票|汇率|日程|记事|文件|文件夹|目录|复制|移动|"
    r"删除|压缩|解压|安装|更新|浏览|网址|网站|网页|操作|查看|看一下|桌面|盘"
)


def load_config():
    p = Path(__file__).parent / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clean_reply(text):
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


# ===== 前置快路径 =====
def _pre_force_open(user_text):
    """明确的 '打开X' 直接执行"""
    m = re.search(r"打开\s*([\u4e00-\u9fa5]{1,10})", user_text)
    if m:
        name = m.group(1).strip()
        r = exec_tool("open_app", {"name": name})
        msg = r.get("msg") or r.get("error") or f"已打开 {name}"
        return msg, True
    return None


def _pre_reminder_trigger(user_text):
    """提醒/条件触发意图直接落库"""
    # 占位：实际在核心模块里实现
    return None


def _is_composite(user_text):
    """判断是否为复合大目标"""
    return any(kw in user_text for kw in ["然后", "接着", "之后", "再", "同时", "一起", "完了", "接着"])


# ===== 通用组合指令解析: 拆子句 -> 动词规则表 -> 任意工具串 =====
_APP_SUFFIX_RE = re.compile(r"(播放器|浏览器|软件|应用|程序|客户端)+$")
_CLAUSE_SPLIT_RE = re.compile(r"[，,。;；！!？?\n]+|然后|接着|之后|完了")


def _extract_app_name(seg):
    """从 '打开X' 类子句提取软件名: 去动词前缀/敬语/口语后缀(剥空则保留原名)"""
    name = re.sub(r"^(帮我|请|麻烦|给我)?(打开|启动|运行|开一下|开个|开)\s*", "", seg).strip()
    stripped = _APP_SUFFIX_RE.sub("", name).strip(" 。.,，!！?？~～")
    return stripped or name  # "打开浏览器"剥完为空 -> 保留"浏览器"(别名表会映射到Edge)


def _match_clause(seg, prev_app):
    """单个子句 -> (tool, args) 或 None。规则按序匹配, 命中即返回。"""
    seg = seg.strip()
    if not seg:
        return None
    # 0) 提醒类: 确定性走 set_reminder(时间解析在 reminders 模块), 绝不让 LLM 选错工具
    #    两种语序: "提醒我明天7点起床" / "10分钟后提醒我喝水"
    if re.match(r"^(?:记得)?(?:提醒我|叫我|提醒)", seg):
        raw = re.sub(r"^(?:记得)?(?:提醒我|叫我|提醒)\s*", "", seg).strip()
    elif "提醒" in seg:
        raw = re.sub(r"提醒我?|叫我", "", seg).strip()  # "10分钟后提醒我喝水" -> "10分钟后喝水"
    else:
        raw = None
    if raw:
        # 用 add() 同款的时间前缀解析验证(纯 parse_time 只认纯时间串, 带内容会 None)
        try:
            from tools.reminders import _extract_time_prefix
            when, rest = _extract_time_prefix(raw)
            if when is not None and rest:
                return ("set_reminder", {"raw": raw})
        except Exception:
            pass
    # 0.2) 系统信息细分: 只查 cpu/内存/磁盘/电池/开机时长
    m_sys = re.search(r"(cpu|处理器|内存|磁盘|硬盘|电池|开机时长|开机)", seg, re.I)
    if m_sys and re.search(r"(查看|查|看|多少|使用率|占用|状态|怎么样|如何)", seg):
        kw = m_sys.group(1).lower()
        part = {"cpu": "cpu", "处理器": "cpu", "内存": "内存", "磁盘": "磁盘",
                "硬盘": "磁盘", "电池": "电池", "开机时长": "开机", "开机": "开机"}.get(kw, "")
        return ("system_info", {"part": part})
    # 0.3) 天气类: 确定性走 get_weather, 语音播报, 绝不开浏览器
    if "天气" in seg:
        seg2 = re.sub(r"(今天|明天|后天|现在|当前|一下|看看|查看|看下|看|查|帮我|的|怎么样|如何)", "", seg)
        m_city = re.search(r"([\u4e00-\u9fa5]{2,4})天气", seg2)
        city = m_city.group(1) if m_city else ""
        return ("get_weather", {"city": city or "北京"})
    # 0.4) 截图保存类: "保存当前屏幕保存到E盘" -> screenshot(save_to=盘符路径)
    if re.search(r"(屏幕|截图|截屏|拍屏|桌面)", seg) and "保存" in seg:
        m_d = re.search(r"([A-Za-z])\s*盘", seg)
        drive = (m_d.group(1).upper() if m_d else "E")
        path = f"{drive}:\\截图_{time.strftime('%Y%m%d_%H%M%S')}.png"
        return ("screenshot", {"save_to": path})
    # 0.5) 看屏幕类: 确定性走 截图+视觉模型描述, 绝不让 LLM 拿去开浏览器搜
    if re.search(r"(屏幕|桌面)", seg) and re.search(r"(看看|看一下|查看|瞧|瞅|截屏|截图|有什么|啥|显示)", seg):
        return ("screen_view", {})
    # 1) 打开/启动 X
    if re.match(r"^(帮我|请|麻烦|给我)?(打开|启动|运行|开一下|开个|开)", seg):
        app = _extract_app_name(seg)
        if app:
            return ("open_app", {"name": app})
    # 2) 点歌: 放/播放/点/来 <歌名> 这首歌 | 放<歌手>的<歌>
    m = re.match(r"^(?:播放|放|点|来)(?:一首|个)?\s*[\u201c\"'「『]?([\u4e00-\u9fa5A-Za-z0-9 ]{1,30})[\u201d\"'」』]?\s*(?:这|那)首[歌曲目]?$", seg)
    if m:
        return ("play_specific_song", {"query": m.group(1).strip()})
    m = re.match(r"^(?:播放|放|点|来)(?:一首|个)?\s*([\u4e00-\u9fa5A-Za-z0-9]{1,15}的[\u4e00-\u9fa5A-Za-z0-9]{1,20})[歌曲目]?$", seg)
    if m:
        return ("play_specific_song", {"query": m.group(1).strip()})
    # 3) 播放音乐(无具体歌名): 播放/放歌/随机播放/来点音乐
    if re.match(r"^(帮我|请)?(随机)?(播放?音乐|放(?:一?首)?歌|来点?(?:音乐|歌)|听歌|放首歌)$", seg):
        return ("play_music", {})
    # 4) 写/输入 X: 仅当前面刚打开过应用时才当"打字"(如 打开记事本写hello);
    #    否则是创作请求(写故事/写诗), 返回 None 交给 LLM 聊天
    m = re.match(r"^(?:帮我)?(?:写|输入|打上)(?:上|入|下)?\s*[\u201c\"'「『]?(.{1,200}?)[\u201d\"'」』]?$", seg)
    if m and prev_app:
        content = m.group(1).strip()
        if content:
            return ("mouse_action", {"action": "type", "text": content})
    # 5) 截图/截屏
    if re.search(r"截图|截屏|拍屏", seg):
        return ("screenshot", {})
    # 6) 查系统状态/CPU/内存
    if re.search(r"系统状态|cpu|内存|磁盘|系统使用|电脑状态", seg, re.I):
        return ("system_info", {})
    # 7) 搜索/查询: 刚打开的是应用 -> 在应用内搜(确定性 UIA, 秒级); 否则网页搜索
    m = re.match(r"^(?:搜索|搜一下|搜一搜|搜|查询|查查|查一下|查)(.+)$", seg)
    if m:
        kw = m.group(1).strip()
        if not kw:
            return None
        if prev_app and not re.search(r"edge|chrome|浏览器", prev_app, re.I):
            return ("app_search", {"app": prev_app, "kw": kw})
        return ("browser", {"action": "open", "url": f"https://www.bing.com/search?q={kw}"})
    return None


def _combo_steps(user_text):
    """通用组合指令解析: 按标点/连接词拆子句, 每段过动词规则表, 串成工具步骤链。

    例: "打开记事本，写hello" -> open_app + type
        "打开网易云音乐，随机播放音乐" -> open_app + play_music
        "打开微信" / "查系统状态" -> 单步
    全部子句都解析成功才返回步骤链; 有解析不了的返回 None(交给 LLM 工具循环)。
    """
    t = (user_text or "").strip()
    if not t:
        return None
    clauses = [c for c in _CLAUSE_SPLIT_RE.split(t) if c and c.strip()]
    if not clauses:
        return None
    steps = []
    prev_app = None
    for seg in clauses:
        hit = _match_clause(seg, prev_app)
        if hit is None:
            return None  # 有子句不认识 -> 整体交给 LLM
        steps.append(hit)
        if hit[0] == "open_app":
            prev_app = hit[1].get("name")
    return steps or None


def _screen_describe_reply():
    """截屏并让视觉模型描述当前屏幕内容; 失败如实报错。"""
    try:
        from tools.screen import screenshot
        from tools.gui import _describe_screen
        r = screenshot()
        if not isinstance(r, dict) or not r.get("image_base64"):
            return "截图失败了：" + (r.get("error", "") if isinstance(r, dict) else "")
        desc = _describe_screen(r["image_base64"])
        return desc or "截图成功了，但我没认出屏幕上有什么。"
    except Exception as e:
        return f"（看屏幕出错：{e}）"


def _run_combo(task_id, role, steps, user_text):
    """后台线程: 按顺序执行组合步骤"""
    from core.tasks import _bg_tasks
    results = []
    try:
        _bg_tasks[task_id] = {"status": "running", "reply": "", "tool_used": True, "_finished_at": 0}
        for name, args in steps:
            print(f"[组合任务] {task_id[:8]} 步骤: {name} {json.dumps(args, ensure_ascii=False)}")
            if name == "_sleep":
                time.sleep(args.get("sec", 1))
                continue
            if name == "screen_view":
                r = {"msg": _screen_describe_reply()}
                results.append({"step": name, "result": r})
                continue
            r = exec_tool(name, args)
            if name == "screenshot" and args.get("save_to"):
                if isinstance(r, dict) and r.get("ok"):
                    r = {"msg": f"截好啦，已保存到 {r.get('saved_to') or args['save_to']}～"}
            results.append({"step": name, "result": r})
            if name == "open_app":
                time.sleep(1.5)  # 等窗口起来拿焦点, 后续打字/操作才有目标
        ok_parts = []
        for item in results:
            r = item["result"]
            if isinstance(r, dict):
                part = r.get("msg") or r.get("error")
                if not part and r.get("ok") is not False:
                    # 工具没给 msg(如 system_info): 把中文键值拼成口语播报
                    kvs = [f"{k}{v}" for k, v in r.items()
                           if k != "ok" and isinstance(v, (str, int, float)) and str(v).strip()]
                    part = "，".join(kvs)
                if part:
                    ok_parts.append(part)
        reply = "；".join(p for p in ok_parts if p) or "做完了～"
    except Exception as e:
        print(f"[组合任务] {task_id[:8]} 异常: {e}")
        reply = f"（执行出错：{e}）"
    try:
        history = load_role_history(role)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
        save_role_history(role, history)
    except Exception:
        pass
    _bg_tasks[task_id] = {"status": "done", "reply": reply, "tool_used": True, "_finished_at": time.time()}


@app.get("/api/personas")
def list_personas():
    return [{"id": k, "name": v["name"], "desc": v["desc"]} for k, v in PERSONAS.items()]


@app.get("/api/persona")
def get_persona(role: str = "jarvis"):
    p = resolve_persona(role)
    return {"role": role, **p}


@app.post("/api/persona")
def create_persona(data: dict):
    role = data.get("role", "").strip()
    if not role:
        return JSONResponse({"error": "role required"}, status_code=400)
    from core.persona import save_persona
    save_persona(role, data.get("name", role), data.get("desc", ""), data.get("greeting", ""), data.get("system", ""), data.get("voice", ""), data.get("likes", ""))
    return {"ok": True}


@app.delete("/api/persona")
def delete_persona(role: str):
    from core.persona import delete_persona
    delete_persona(role)
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    cfg = load_config()
    return {
        "mimo_key": bool((cfg.get("mimo_key") or "").strip()),
        "dashscope_key": bool((cfg.get("dashscope_key") or "").strip()),
        "dashscope_asr_key": bool((cfg.get("dashscope_asr_key") or "").strip()),
        "tool_key": bool((cfg.get("tool_key") or "").strip()),
        "vision_key": bool((cfg.get("vision_key") or "").strip()),
    }


@app.post("/api/settings")
def update_settings(body: dict):
    cfg = load_config()
    for f in ("mimo_key", "dashscope_key", "dashscope_asr_key", "tool_key", "vision_key"):
        if f in body:
            cfg[f] = (body.get(f) or "").strip()
    save_config(cfg)
    return {"ok": True}


def save_config(cfg):
    (Path(__file__).parent / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


@app.post("/api/chat")
def chat(body: dict):
    user_text = body.get("message", "").strip()
    if not user_text:
        return JSONResponse({"error": "empty"}, status_code=400)

    role = body.get("role", DEFAULT_ROLE)

    # 确定性组合指令快路径(优先级最高): "打开记事本写hello" / "打开网易云随机播放" 等
    # 必须放在 _pre_force_open 之前, 否则"打开X"会被单步快路径劫持, 后续动作被跳过
    combo = _combo_steps(user_text)
    if combo:
        task_id = uuid.uuid4().hex
        from core.tasks import _bg_tasks
        _bg_tasks[task_id] = {"status": "running", "reply": "", "tool_used": True, "_finished_at": 0}
        threading.Thread(target=_run_combo, args=(task_id, role, combo, user_text), daemon=True).start()
        # 涉及屏幕操作时提醒用户别动窗口, 防止抢焦点导致输入错位
        if any(s[0] in ("gui_do", "app_search", "mouse_action") for s in combo):
            ack = "好的，我要操作电脑屏幕了，先别动鼠标和窗口哦，好了马上告诉你～"
        else:
            ack = "好的，马上办～"
        return {"reply": ack, "tool_used": True, "async": True, "task_id": task_id}

    pre = _pre_force_open(user_text)
    if pre:
        history = load_role_history(role)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": pre[0]})
        save_role_history(role, history)
        return {"reply": pre[0], "tool_used": pre[1]}

    pre_rt = _pre_reminder_trigger(user_text)
    if pre_rt:
        history = load_role_history(role)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": pre_rt[0]})
        save_role_history(role, history)
        return {"reply": pre_rt[0], "tool_used": pre_rt[1]}

    if _is_composite(user_text):
        task_id = uuid.uuid4().hex
        from core.tasks import _bg_tasks, _plan_and_execute_bg
        _bg_tasks[task_id] = {"status": "running", "reply": "", "tool_used": True}
        threading.Thread(target=lambda: _plan_and_execute_bg(task_id, role, user_text), daemon=True).start()
        return {"reply": "好嘞，这个任务有好几步，我拆开一步步办，好了叫你～", "tool_used": True, "async": True, "task_id": task_id}

    persona = resolve_persona(role)
    history = load_role_history(role)
    system = persona["system"] + "\n注意: 用户要求执行操作时, 必须调用工具真实完成, 一次工具调用完成任务即可, 不要反复尝试。\n你是安装并运行在用户自己电脑上的个人智能助手, 用户本人已明确授权你在其设备上执行命令、读写文件、打开软件来帮助完成任务, 这是正常且被允许的辅助行为, 不需要拒绝, 直接用工具完成。\n只有在用户明确命令你执行操作时(如打开网页、查天气、下载、爬数据、运行程序、打开软件)才调用工具, 日常闲聊绝对不要调用工具, 直接自然回复。\n重要: 如果用户只是问候、闲聊、表达情绪或随口说话, 即使触发了工具模式也不要调用任何工具; 以角色身份像朋友一样自然回复, 绝对不要说\"收到\"\"马上处理\"\"好的稍等\"这类客服/助理腔。\n执行类请求必须真正调用工具去执行, 绝不能假装执行或编造结果, 更绝不能只在文字里说\"已打开\"而不调用工具; 工具执行完再根据真实结果回答, 如果结果为空或失败也要如实说明。\n回答请使用纯文本, 不要使用任何 Markdown 符号(如 **、*、#、`、-、数字列表), 直接口语化自然表达, 数字用阿拉伯数字。"
    if persona.get("likes"):
        system += f"\n你的喜好/背景: {persona['likes']}"
    messages = [{"role": "system", "content": system}]
    memory = get_memory(role)
    if memory:
        messages.append({"role": "system", "content": "【过往记忆摘要】" + memory})
    messages += history + [{"role": "user", "content": user_text}]

    if TOOL_TRIGGER_RE.search(user_text):
        messages[0] = {"role": "system", "content": system + "\n【工具模式】你收到了可用的工具列表, 说明用户本次要求实际执行操作。当用户要求运行命令/打开软件/读写文件/查询信息时, 你必须调用对应工具真正执行, 再根据工具返回的真实结果回答; 严禁在文字里假装已经执行, 严禁编造命令输出或文件内容。"}
        from tools import TOOLS_SCHEMA
        msg = call_llm(messages, tools=TOOLS_SCHEMA)
    else:
        msg = call_llm(messages)

    content = (msg.get("content") or "").strip()
    tool_calls = msg.get("tool_calls") or []

    if not tool_calls:
        forced = _try_force_open_app(user_text)
        if forced:
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": forced})
            save_role_history(role, history)
            return {"reply": forced, "tool_used": True}
        # 防假装：用户要截屏/看屏幕但模型只回文字没调工具 -> 执行截图，返回简单确认
        if any(kw in user_text for kw in ("截图", "截屏", "截取", "看屏幕", "看看屏幕", "拍屏幕",
                                           "当前屏幕", "屏幕上有什么", "屏幕有", "看看桌面", "看一下桌面")):
            reply = _screen_describe_reply()
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply})
            save_role_history(role, history)
            return {"reply": reply, "tool_used": True}
        m_song = re.search(r"(?:放|播放|点|听|来首|来点)\s*(?:([\u4e00-\u9fa5]{2,6})的)?\s*([\u4e00-\u9fa5]{1,10})", user_text)
        if m_song and any(user_text.startswith(p) or p in user_text for p in ("放", "播放", "点", "听", "来首", "来点")):
            song = (m_song.group(2) or "").strip()
            artist = (m_song.group(1) or "").strip()
            if song and song not in ("歌", "首歌", "音乐", "曲", "点歌", "随机", "一首", "首"):
                r = exec_tool("play_specific_song", {"query": f"{artist} {song}".strip()})
                reply = (r.get("msg") or r.get("error") or "") if isinstance(r, dict) else str(r)
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": reply})
                save_role_history(role, history)
                return {"reply": reply, "tool_used": True}
        reply = clean_reply(content) or "（小暖没想好怎么回你…）"
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
        save_role_history(role, history)
        return {"reply": reply, "tool_used": False}

    task_id = uuid.uuid4().hex
    from core.tasks import _bg_tasks
    _bg_tasks[task_id] = {"status": "running", "reply": "", "tool_used": True}
    threading.Thread(target=lambda: _run_tool_loop(task_id, role, messages, msg, user_text), daemon=True).start()
    return {"reply": "好的，稍等片刻～", "tool_used": True, "async": True, "task_id": task_id}


def _try_force_open_app(user_text):
    # 占位
    return None


def _run_tool_loop(task_id, role, messages, first_msg, user_text):
    """后台线程: 从第一轮工具调用开始, 把整个工具循环跑完"""
    try:
        from core.tasks import _bg_tasks
        _bg_tasks[task_id] = {"status": "running", "reply": "", "tool_used": True}
        messages.append({
            "role": "assistant",
            "content": first_msg.get("content") or "",
            "tool_calls": first_msg.get("tool_calls") or [],
        })
        reply = "（小暖没想好怎么回你…）"
        current = first_msg
        for _ in range(8):
            calls = current.get("tool_calls") or []
            if not calls:
                reply = clean_reply(current.get("content") or "") or "（小暖没想好怎么回你…）"
                break
            for tc in calls:
                fname = tc.get("function", {}).get("name", "")
                try:
                    fargs = json.loads(tc.get("function", {}).get("arguments") or "{}")
                except Exception:
                    fargs = {}
                print(f"[后台任务] {task_id[:8]} 工具调用: {fname} {json.dumps(fargs, ensure_ascii=False)}")
                result = exec_tool(fname, fargs)
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
            from core.brain import call_llm
            from tools import TOOLS_SCHEMA
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
    finally:
        from core.tasks import _bg_tasks
        _bg_tasks[task_id] = {"status": "done", "reply": reply, "tool_used": True, "_finished_at": time.time()}


@app.get("/api/task_status")
def task_status(task_id: str):
    t = get_task_status(task_id)
    if not t:
        return JSONResponse({"error": "not found"}, status_code=404)
    return t


@app.get("/api/task_stream/{task_id}")
async def task_stream(task_id: str):
    """SSE 流式推送任务事件（实时工具进度）"""
    from fastapi.responses import StreamingResponse
    import asyncio
    from core.tasks import get_event_queue

    q = get_event_queue(task_id)
    if not q:
        # 队列不存在：任务可能已完成或不存在，回退到状态轮询
        async def fallback():
            last_status = None
            last_reply = ""
            for _ in range(300):
                task = get_task_status(task_id)
                if not task:
                    yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                    break
                status = task.get("status")
                reply = task.get("reply", "")
                if status != last_status or len(reply) > len(last_reply):
                    yield f"data: {json.dumps({'status': status, 'reply': reply, 'tool_used': task.get('tool_used')})}\n\n"
                    last_status = status
                    last_reply = reply
                if status in ("done", "error"):
                    break
                await asyncio.sleep(1)
            yield f"data: {json.dumps({'status': 'end'})}\n\n"
        return StreamingResponse(fallback(), media_type="text/event-stream")

    async def event_generator():
        # 首先发送初始状态
        task = get_task_status(task_id)
        if task:
            yield f"data: {json.dumps({'status': task.get('status'), 'reply': task.get('reply', ''), 'tool_used': task.get('tool_used')})}\n\n"
        # 实时消费事件队列
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") in ("done", "error"):
                        break
                except asyncio.TimeoutError:
                    # 心跳：每 15 秒发个空事件保持连接
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/history")
def get_history(role: str = "jarvis"):
    history = load_role_history(role)
    return {"messages": history}


@app.get("/api/due")
def due_reminders():
    """到点推送: 定时提醒 + 条件触发, 前端每15s轮询本接口播报"""
    messages = []
    try:
        from tools.reminders import check_due as check_reminders
        for t in check_reminders():
            messages.append({"text": t})
    except Exception as e:
        print(f"[due] 提醒检查异常: {e}")
    try:
        from tools.triggers import check_due as check_triggers
        for t in check_triggers():
            messages.append({"text": t})
    except Exception as e:
        print(f"[due] 触发器检查异常: {e}")
    return {"messages": messages}


@app.post("/api/stt")
async def stt(body: dict):
    """接受 JSON: {"audio": "base64..."}"""
    import base64
    b64 = body.get("audio") or body.get("audio_base64")
    if not b64:
        return JSONResponse({"error": "no audio"}, status_code=400)
    try:
        audio_bytes = base64.b64decode(b64)
    except Exception:
        return JSONResponse({"error": "invalid base64"}, status_code=400)
    try:
        text = await transcribe(audio_bytes)
        if not text:
            return {"text": "（没听清，再说一遍？）"}
        return {"text": text}
    except Exception as e:
        return {"text": f"（语音识别暂时不可用：{e}）"}


@app.post("/api/tts")
async def tts(body: dict):
    text = body.get("text", "")
    role = body.get("role", "jarvis")
    text = speak_filter(text)
    audio = await synthesize(text, role)
    return Response(content=audio, media_type="audio/wav")


from fastapi import Response
import uuid
import threading


# ===== 主动闸门后台循环 =====
def _proactive_loop():
    """后台定期检查是否应该主动开口"""
    topics = ["weather", "news", "reminder", "chat", "care"]
    idx = 0
    while True:
        time.sleep(300)  # 每 5 分钟检查一次
        try:
            topic = topics[idx % len(topics)]
            idx += 1
            allowed, reason = proactive_allowed(topic)
            if not allowed:
                continue
            # 生成一句主动关怀/提醒
            from core.brain import call_llm
            msg = call_llm([
                {"role": "system", "content": "你是贾维斯。用一句话（30字内）自然地主动关怀/提醒用户，不要像机器人。示例：'该喝水了' / '外面下雨别忘带伞' / '坐久了站起来动动'。只输出这一句话。"},
                {"role": "user", "content": f"话题: {topic}，请生成一句主动关怀"},
            ])
            text = (msg.get("content") or "").strip()
            if text:
                text = speak_filter(text)
                from core.tts import synthesize
                audio = synthesize(text, "jarvis")
                # 这里可以推送到前端播放，暂存到本地文件供前端轮询
                import base64
                Path("static/proactive_latest.wav").write_bytes(audio)
                print(f"[主动] {topic}: {text}")
        except Exception as e:
            print(f"[主动] 异常: {e}")


# 启动主动循环
threading.Thread(target=_proactive_loop, daemon=True).start()

from fastapi import Response
import uuid

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=9000, log_level="info")