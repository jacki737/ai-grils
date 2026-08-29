"""屏幕 GUI 操作闭环(眼睛): 截屏 -> VLM 理解 -> 动作JSON -> 执行 -> 复核 -> 循环
参考 Nolan eyes.py: 坐标换算 / UIA 控件树吸附 / 复核闭环 / 诚实失败报告 / FAILSAFE

闭环主流程(gui_do), 每步循环:
  0) 若给了 target_hint, 先把目标窗口置前(防被其他窗口遮挡截图);
  1) 感知: 截屏(screen.screenshot) + UIA 控件树(gui_helper.ps1), 控件树带物理坐标;
  2) 思考: 把截图+控件清单发给 VLM(vision._ask_vlm), 让它返回下一步动作 JSON;
  3) 终态判定: 返回 done 必须先过"复核"确认真的完成, 防谎报; fail 需诚实;
  4) 执行: 坐标从截图尺寸换算成物理像素, 优先按控件名精确定位, 再鼠标/键盘落地;
  5) 复核: 带 expect 的动作重新截屏问 VLM 是否生效(未生效换策略);
  6) 保护: FAILSAFE(鼠标被甩到屏幕角落立即中止)/死循环检测/步数上限。
执行全部走 static/gui_helper.ps1(PowerShell), 中文经 base64/临时文件传参。
"""
import json
import logging
import os
import re
import subprocess
import time

from ._paths import STATIC_DIR
from .screen import _win_temp_paths, screenshot
from .vision import _ask_vlm, _ask_vlm_once, _vision_config

_log = logging.getLogger("gui")

# Windows 侧执行器脚本路径(gui_helper.ps1 支持 screen/uia/mouse/type/key/front 等动作)
_GUI_HELPER = os.path.join(STATIC_DIR, "gui_helper.ps1")

# 视觉模型思考 prompt: 决定下一步动作, 返回 JSON
# 注意: glm-4v 这类模型在开放问答里容易"不敢动", 总是回 fail。
# 因此 prompt 里强制要求: 必须给出具体动作, 只有极少数情况才允许 fail。
_GUI_SYSTEM = (
    "你是贾维斯的屏幕操作大脑。你看着电脑屏幕截图，根据当前任务决定下一步动作。\n"
    "只返回一个 JSON 对象（不要任何多余文字、不要 markdown 代码块）：\n"
    '{"action": "left_click|double_click|type|key|scroll|wait|done|fail", '
    '"x": 截图坐标X, "y": 截图坐标Y, '
    '"text": "点击目标文字(如按钮名)或要输入的内容", '
    '"keys": "组合键如 ctrl+s 或单键 enter", '
    '"thought": "一句话理由", "expect": "执行后屏幕上预期出现的现象"}\n'
    "规则：\n"
    "- 你正在真实操作系统界面，必须想办法推进任务，禁止空谈、禁止轻易 fail。\n"
    "- 坐标基于截图尺寸（宽不超过1280），不是物理像素，由系统自动换算；\n"
    "- 点按钮/入口优先在 text 里给出目标文字，系统会按名精确定位；\n"
    "- 输入文字：先 left_click 点击目标输入框/文本框（text 里给它的名称或位置），再 type；\n"
    "  type 的 text 必须是任务要求输入的精确内容，一字不改，不要写描述；\n"
    "- 滚动用 scroll（text 填 up 或 down）；\n"
    "- 只要界面上有看起来能推进任务的按钮/条目，就返回具体点击动作（例如播放/暂停按钮、"
    "歌单里的第一首歌、确定按钮、登录入口），不要犹豫；\n"
    "- 任务真正完成后才返回 done；只有明确无法完成（界面空白、需要扫码登录、明确报错）才 fail 并说明原因；\n"
    "- 安全禁令：禁止输入密码、禁止支付、禁止删除文件、禁止向联系人发消息，\n"
    "遇到此类界面必须返回 fail。\n"
)

# 复核 prompt: 只看截图实际可见内容回答是非题, 拿不准一律 false
_GUI_VERIFY_SYSTEM = (
    "你是贾维斯的执行复核模块。我会给你一张电脑屏幕截图和一个判断问题，"
    "你只根据截图中实际可见的内容回答，绝不猜测、绝不脑补。\n"
    "只返回一个 JSON 对象（不要任何多余文字、不要 markdown 代码块）：\n"
    '{"ok": true或false, "reason": "一句话依据"}\n'
    "拿不准时返回 false 并在 reason 里说明缺什么。"
)

_VLM_FALLBACK_MODEL = "glm-4v-flash"
_VLM_FALLBACK_BASE = "https://open.bigmodel.cn/api/paas/v4"
_VLM_FALLBACK_KEY = ""

# 应用名/窗口提示词 -> 进程名: 置前兜底用。
# 关键场景: 网易云音乐窗口标题是当前歌曲名(如 "Call When You Can - aron!/dodie"),
# 用 target_hint="网易云音乐" 按标题永远找不到窗口, 必须按进程名 cloudmusic 兜底置前。
_APP_PROC = {
    "网易云音乐": "cloudmusic", "网易云": "cloudmusic", "云音乐": "cloudmusic",
    "记事本": "notepad", "notepad": "notepad",
    "微信": "wechat", "wechat": "wechat",
    "chrome": "chrome", "谷歌": "chrome", "google": "chrome",
    "edge": "msedge", "浏览器": "msedge",
    "qq音乐": "QQMusic", "qqmusic": "QQMusic",
    "spotify": "Spotify",
    "计算器": "calc", "calc": "calc",
    "今日头条": "toutiao", "头条": "toutiao", "toutiao": "toutiao",
}


def _find_hwnd_by_title(title_substr):
    """按窗口标题子串找首个可见顶层窗口句柄, 找不到返回 0。"""
    import ctypes
    user32 = ctypes.windll.user32
    needle = (title_substr or "").strip().lower()
    if not needle:
        return 0
    hit = [0]

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            sb = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, sb, n + 1)
            if needle in sb.value.lower():
                hit[0] = hwnd
                return False
        return True

    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    try:
        user32.EnumWindows(ENUMPROC(cb), 0)
    except Exception:
        pass
    return hit[0]


def _bring_front(hwnd):
    """把窗口置前拿焦点(AttachThreadInput 方案, 与 play_specific_song 一致)。"""
    import ctypes
    user32 = ctypes.windll.user32
    fore = user32.GetForegroundWindow()
    fore_tid = user32.GetWindowThreadProcessId(fore, None) if fore else 0
    cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = False
    if fore_tid and fore_tid != cur_tid:
        attached = bool(user32.AttachThreadInput(cur_tid, fore_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(cur_tid, fore_tid, False)
    time.sleep(0.3)


def app_search(app="", kw=""):
    """在指定应用里搜索关键词(确定性 UIA, 秒级): 找窗口 -> 置前 -> 搜索框写值 -> 回车。

    UIA 找不到搜索框时回退视觉闭环 gui_do(慢但通用)。
    返回 {"ok": True, "msg": ...} 或 {"ok": False, "error": ...}。
    """
    from . import uia as _uia
    app = (app or "").strip()
    kw = (kw or "").strip()
    if not app or not kw:
        return {"ok": False, "error": "需要 app 和 kw 两个参数"}
    proc = _APP_PROC.get(app) or _APP_PROC.get(app.lower()) or app.replace(" ", "").lower()
    try:
        hwnd = _find_proc_hwnd(proc) or _find_hwnd_by_title(app)
        if not hwnd:
            from .apps import open_app
            open_app(name=app)
            for _ in range(10):
                time.sleep(1.5)
                hwnd = _find_proc_hwnd(proc) or _find_hwnd_by_title(app)
                if hwnd:
                    break
        if not hwnd:
            # 诚实失败: 绝不往别的前台窗口里乱打字
            return {"ok": False,
                    "error": f"没找到{app}的窗口(可能未安装或没启动成功)，无法在它里面搜索"}

        _bring_front(hwnd)
        # 置前校验: 前台必须真的是目标窗口, 否则粘贴会进别的应用
        import ctypes
        if ctypes.windll.user32.GetForegroundWindow() != hwnd:
            time.sleep(0.5)
            _bring_front(hwnd)
            if ctypes.windll.user32.GetForegroundWindow() != hwnd:
                return {"ok": False, "error": f"{app}窗口置前失败，取消搜索以免误操作其他窗口"}

        # 搜索框写值(UIA ValuePattern), 失败先 Esc 退全屏态再试一次
        import ctypes
        ok = _uia.set_edit_value(hwnd, "", kw)
        if not ok:
            user32 = ctypes.windll.user32
            user32.keybd_event(0x1B, 0, 0, 0)   # Esc down
            user32.keybd_event(0x1B, 0, 2, 0)   # Esc up
            time.sleep(0.8)
            ok = _uia.set_edit_value(hwnd, "", kw)
        if not ok:
            # 路2: UIA 拿搜索框坐标 -> 真实点击聚焦 -> 粘贴 -> 回车
            try:
                controls = _gui_controls(app)
                if not controls:
                    return {"ok": False, "error": f"{app}窗口枚举不到控件，无法定位搜索框"}
                edit_xy = None
                # 搜索框一定在窗口顶部: 优先 edit/combobox, 按 y 升序取最靠上的;
                # 绝不拿 document(整个页面区域, 中心在页面中间, 点了没用)
                cands = [c for c in controls
                         if c.get("type") in ("edit", "combobox")
                         and c["rect"][2] > 60 and c["rect"][3] > 10]
                if not cands:
                    cands = [c for c in controls if c.get("type") == "document"]
                if cands:
                    cands.sort(key=lambda c: c["rect"][1])  # y 升序 = 最靠顶
                    rx, ry, w, h = cands[0]["rect"]
                    edit_xy = (rx + w // 2, ry + h // 2)
                if edit_xy:
                    print(f"[app_search] 点击搜索框({edit_xy[0]},{edit_xy[1]})后粘贴")
                    _run_gui_helper(["-Action", "mouse", "-X", str(edit_xy[0]), "-Y", str(edit_xy[1]), "-Keys", "left_click"], timeout=20)
                    time.sleep(0.4)
                    import base64 as _b64
                    tb = _b64.b64encode(kw.encode("utf-8")).decode("ascii")
                    _run_gui_helper(["-Action", "type", "-TextB64", tb], timeout=20)
                    time.sleep(0.3)
                    ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0x0D, 0, 2, 0)
                    return {"ok": True, "msg": f"已在{app}里搜索：{kw}"}
            except Exception as exc:
                print(f"[app_search] 坐标点击路径失败: {exc}")
        if not ok:
            # 路3: 视觉闭环兜底(慢但通用)
            print(f"[app_search] {app} UIA 找不到搜索框, 回退视觉闭环")
            r = gui_do(task=f"在{app}里搜索 {kw}", target_hint=app, max_steps=6)
            return {"ok": True, "msg": r}

        time.sleep(0.3)
        user32 = ctypes.windll.user32
        user32.keybd_event(0x0D, 0, 0, 0)   # Enter down
        user32.keybd_event(0x0D, 0, 2, 0)   # Enter up
        return {"ok": True, "msg": f"已在{app}里搜索：{kw}"}
    except Exception as e:
        return {"ok": False, "error": f"{app}内搜索失败：{e}"}


def _front_target(target_hint):
    """把目标窗口置前(并最大化盖住其他窗口, 让视觉模型只看得到目标应用)。
    优先按标题子串匹配; 匹配不到(标题是歌曲名等)再用进程名兜底。
    置前失败静默(截屏会照拍, 交给视觉复核兜底)。"""
    hint = (target_hint or "").strip()
    if not hint:
        return
    try:
        out = _run_gui_helper(["-Action", "front", "-Window", hint, "-Max", "1"], timeout=10)
        if out and "notfound" not in out:
            return
    except Exception:
        pass
    proc = _APP_PROC.get(hint)
    if not proc:
        for k, v in _APP_PROC.items():
            if len(k) >= 2 and (k in hint or hint in k):
                proc = v
                break
    if proc:
        try:
            _run_gui_helper(["-Action", "frontapp", "-Window", proc, "-Max", "1"], timeout=10)
        except Exception:
            pass


def _run_gui_helper(args, timeout=30):
    """调 Windows 侧 gui_helper.ps1, 返回 stdout(UTF-8 解码)。失败抛异常。"""
    p = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", _GUI_HELPER] + list(args),
        capture_output=True, timeout=timeout,
    )
    return (p.stdout or b"").decode("utf-8", "replace").strip()


def _screen_size():
    """物理屏幕分辨率(DPI 感知后), 与截图工具一致。"""
    out = _run_gui_helper(["-Action", "screen"], timeout=15)
    m = re.match(r"(\d+)x(\d+)", out)
    if not m:
        return 1280, 720
    return int(m.group(1)), int(m.group(2))


def _screenshot_dims(sw, sh):
    """发送给 VLM 的截图尺寸: 宽 <= 1280, 与 screenshot() 缩放逻辑一致。"""
    if sw > 1280:
        return 1280, round(sh * 1280 / sw)
    return sw, sh


def _num(v, default=0.0):
    """把 VLM 返回的坐标容错成 float。Qwen 类模型偶尔返回 ["123"]/[123,456]/
    "123, 456"/"123px" 等畸形形式, 这里取第一个合法数字, 取不到用默认值。"""
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, (list, tuple)):
        for item in v:
            r = _num(item, None)
            if r is not None:
                return r
        return float(default)
    if isinstance(v, dict):
        for k in ("x", "y", "value", "center"):
            if k in v:
                r = _num(v[k], None)
                if r is not None:
                    return r
        return float(default)
    s = re.sub(r"[^\d.\-]", " ", str(v))
    m = re.search(r"-?\d+(\.\d+)?", s)
    if m:
        return float(m.group(0))
    return float(default)


def _vlm_to_screen(x, y, shot_w, shot_h):
    """VLM 截图像素 -> 屏幕物理像素: 实际坐标 = VLM坐标 x (物理宽/截图宽), 钳制在屏幕内。"""
    sw, sh = _screen_size()
    px = int(round(x * sw / max(shot_w, 1)))
    py = int(round(y * sh / max(shot_h, 1)))
    px = max(0, min(px, sw - 1))
    py = max(0, min(py, sh - 1))
    return px, py


def _gui_controls(window=""):
    """UIA 控件树枚举: 默认前台窗口, 或按标题子串匹配。返回 [{name,type,rect:(x,y,w,h),enabled}]。"""
    import uuid as _uuid
    fname = "gui_ctl_" + _uuid.uuid4().hex[:8] + ".json"
    win_path, wsl_path = _win_temp_paths(fname)
    out = _run_gui_helper(["-Action", "uia", "-Window", window, "-OutFile", win_path], timeout=20)
    if not os.path.exists(wsl_path):
        return []
    try:
        with open(wsl_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
    finally:
        try:
            os.remove(wsl_path)
        except Exception:
            pass


def _format_controls(controls):
    """紧凑文本化控件清单: 「按钮「播放」@(960,540)」。坐标为物理像素矩形中心。"""
    parts = []
    for c in controls or []:
        rx, ry, w, h = c["rect"]
        cx, cy = rx + w // 2, ry + h // 2
        label = c.get("name") or "（无名）"
        parts.append("%s「%s」@(%d,%d)" % (c.get("type", "控件"), label, cx, cy))
    return "；".join(parts)


def _find_element(controls, keyword):
    """按名称子串(大小写不敏感)找第一个匹配控件的中心点; 无匹配返回 None。"""
    needle = (keyword or "").strip().lower()
    if not needle:
        return None
    for c in controls or []:
        if needle in (c.get("name") or "").lower():
            rx, ry, w, h = c["rect"]
            return (rx + w // 2, ry + h // 2)
    return None


def _snap(x, y, controls):
    """坐标吸附: 落在某控件矩形内或距其中心<=24px 时对齐到控件中心(多命中取面积最小者); 否则原样返回。"""
    if not controls:
        return x, y
    best, best_area = None, None
    for c in controls:
        rx, ry, w, h = c["rect"]
        cx, cy = rx + w / 2, ry + h / 2
        inside = rx <= x <= rx + w and ry <= y <= ry + h
        near = (cx - x) ** 2 + (cy - y) ** 2 <= 24 ** 2
        if inside or near:
            area = w * h
            if best is None or area < best_area:
                best = (int(cx), int(cy))
                best_area = area
    return best if best is not None else (int(x), int(y))


class _GuiFailsafe(Exception):
    """FAILSAFE 触发(鼠标被甩到屏幕角落)时抛出, 由 gui_do 统一捕获中止。"""


def _do_gui_action(action, shot_w, shot_h, controls=None):
    """执行单步动作。坐标先换算为物理像素, 有控件清单时再做就近吸附。
    按名定位优先: VLM 在 text 里给出目标文字时, 先用 UIA 按名找精确中心。
    type 走剪贴板粘贴(base64 传中文), 通吃中文输入。返回动作结果字符串。"""
    act = action["action"]

    if act in ("left_click", "double_click", "right_click"):
        target_text = str(action.get("text", "")).strip()
        named_xy = None
        if target_text and controls:
            named_xy = _find_element(controls, target_text)
        if named_xy:
            x, y = named_xy
            print(f"[gui] 按名定位命中「{target_text}」-> ({x},{y})")
        else:
            x, y = _vlm_to_screen(_num(action.get("x")), _num(action.get("y")), shot_w, shot_h)
            x, y = _snap(x, y, controls)
        out = _run_gui_helper(["-Action", "mouse", "-X", str(x), "-Y", str(y), "-Keys", act], timeout=20)
        if out == "ABORT":
            raise _GuiFailsafe()
        return f"{act}@{x},{y}"

    elif act == "scroll":
        if "x" in action and "y" in action:
            x, y = _vlm_to_screen(_num(action["x"]), _num(action["y"]), shot_w, shot_h)
            x, y = _snap(x, y, controls)
        else:
            x, y = -1, -1
        direction = str(action.get("text", "down")).lower()
        out = _run_gui_helper(["-Action", "scroll", "-X", str(x), "-Y", str(y), "-Dir", direction], timeout=20)
        if out == "ABORT":
            raise _GuiFailsafe()
        return f"scroll:{direction}"

    elif act == "type":
        import base64 as _b64
        # 先确定性点进目标输入框: 在控件树里找编辑框/文档区, 点它拿焦点, 再粘贴
        # 否则剪贴板内容会进当前焦点窗口(可能是聊天框/浏览器), 而不是目标软件
        if controls:
            target_text = str(action.get("text", "")).strip()
            edit_xy = None
            for c in controls:
                if c.get("type") in ("edit", "document"):
                    edit_xy = _find_element([c], target_text) or (c["rect"][0] + c["rect"][2] // 2, c["rect"][1] + c["rect"][3] // 2)
                    break
            if edit_xy:
                print(f"[gui] 点入输入框({edit_xy[0]},{edit_xy[1]})后粘贴")
                _run_gui_helper(["-Action", "mouse", "-X", str(edit_xy[0]), "-Y", str(edit_xy[1]), "-Keys", "left_click"], timeout=20)
                time.sleep(0.3)
        tb = _b64.b64encode(str(action.get("text", "")).encode("utf-8")).decode("ascii")
        out = _run_gui_helper(["-Action", "type", "-TextB64", tb], timeout=20)
        if out == "ABORT":
            raise _GuiFailsafe()
        return "typed"

    elif act == "key":
        keys = str(action.get("keys", "")).strip() or "enter"
        out = _run_gui_helper(["-Action", "key", "-Keys", keys], timeout=20)
        if out == "ABORT":
            raise _GuiFailsafe()
        return f"key:{keys}"

    elif act == "wait":
        time.sleep(1.0)
        return "wait"

    return f"noop:{act}"


def _parse_action(raw):
    """从 VLM 回复解析动作 JSON: 剥离 markdown 代码块/前后缀, 严格校验 action 字段。"""
    text = (raw or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    candidate = m.group(0)
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        # 常见笔误: "x": 204, 475, —— y 被写成裸数字, 修复后重试
        if '"y"' not in candidate:
            repaired = re.sub(
                r'("x"\s*:\s*-?\d+)\s*,\s*(-?\d+)(\s*,)',
                r'\1, "y": \2\3', candidate)
            if repaired != candidate:
                try:
                    obj = json.loads(repaired)
                except json.JSONDecodeError:
                    return None
            else:
                return None
        else:
            return None
    legal = {"left_click", "double_click", "type", "key", "scroll", "wait", "done", "fail"}
    if not isinstance(obj, dict) or obj.get("action") not in legal:
        return None
    return obj


def _verify(shot_b64, question):
    """执行复核(闭环核心): 问 VLM 是非题, 返回 (ok, reason)。调用失败/无法解析返回 (None, ""),
    调用方按「复核不可用, 静默放行」处理——复核是可靠性增强, 绝不成为新故障点。"""
    if not shot_b64:
        return None, ""
    try:
        raw = _ask_vlm(shot_b64, question, system=_GUI_VERIFY_SYSTEM)
    except Exception as exc:
        print(f"[gui] 复核调用失败(按放行处理): {exc}")
        return None, ""
    m = re.search(r"\{.*\}", (raw or "").strip(), re.DOTALL)
    if not m:
        return None, ""
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(obj, dict) or not isinstance(obj.get("ok"), bool):
        return None, ""
    return obj["ok"], str(obj.get("reason", ""))


def _describe_screen(shot_b64):
    """失败时补问一句「当前屏幕显示什么」, 用于具体化失败报告。失败返回空串。"""
    if not shot_b64:
        return ""
    try:
        return _ask_vlm(shot_b64, "用一句话客观描述这张屏幕截图当前显示的主要内容"
                                 "（看到了哪些应用的窗口、界面停留大概在什么位置）。").strip()
    except Exception:
        return ""


def _ensure_app_ready(hint):
    """确保目标应用窗口已在屏幕上就绪: 检测窗口 → 缺失则打开 → 等待出现 → 置前。
    参考 Nolan hands.py 的 _ensure_app_ready 模式。
    hint 可以是应用名(网易云音乐)或窗口标题关键词。
    返回 True 表示窗口就绪; 不阻断(失败静默, 交给视觉闭环兜底)。"""
    try:
        from .apps import _resolve_alias, _normalize_app_name
        normalized = _resolve_alias(_normalize_app_name(hint))
        # 先去 front 一下(标题匹配或进程匹配)
        _front_target(hint)
        import time
        time.sleep(0.5)
        # 如果窗口没出现, 尝试打开应用
        check = _run_gui_helper(["-Action", "front", "-Window", normalized or hint], timeout=10)
        if check and "notfound" in check:
            from . import exec_tool
            exec_tool("open_app", {"name": hint})
            time.sleep(3)
            _front_target(hint)
    except Exception:
        pass


def _locate_click(shot_b64, task, shot_w, shot_h):
    """定向兜底: 当视觉模型在开放问答里不敢给动作时, 换更具体的问法——
    直接问「哪个元素该点、坐标在哪」, 拿到坐标就合成一个 left_click 动作。
    这是经过实战验证的做法: glm-4v 给不出完整动作JSON, 但能给出"播放按钮坐标"。
    返回动作 dict(带截图坐标), 失败返回 None。"""
    if not shot_b64:
        return None
    try:
        q = (
            "当前任务：%s。看这张截图，找出最应该被点击的一个界面元素"
            "（按钮/歌曲条目/菜单项/输入框等），给出它的中心坐标。\n"
            "只返回 JSON：{\"text\": \"元素上显示的文字(没有就留空)\", \"x\": 截图坐标X, \"y\": 截图坐标Y}\n"
            "坐标必须是图片内的具体数字，图片宽 %d 高 %d，左上角为原点。不要返回 0,0。" % (task, shot_w, shot_h)
        )
        raw = _ask_vlm(shot_b64, q, system="你是屏幕分析助手。根据截图给出应点击元素与坐标，只返回合法JSON。")
    except Exception:
        return None
    m = re.search(r"\{.*\}", (raw or "").strip(), re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    try:
        x, y = _num(obj.get("x")), _num(obj.get("y"))
    except (KeyError, TypeError, ValueError):
        return None
    if x <= 0 or y <= 0 or x >= shot_w or y >= shot_h:
        return None
    return {
        "action": "left_click",
        "x": x, "y": y,
        "text": str(obj.get("text", "")).strip(),
        "thought": "定向定位到应点击元素",
        "expect": "点击后界面出现预期变化（元素被选中/页面跳转/开始播放等）",
    }


def _join_zh(*parts):
    """中文句读拼接: 去各分句末尾句号后用「。」连接, 保证全文恰好一个结尾句号。"""
    cleaned = [p.strip().rstrip("。") for p in parts if p and p.strip()]
    return "。".join(cleaned) + "。"


def gui_do(task="", target_hint="", max_steps=8):
    """屏幕感知 + GUI 动作闭环: 逐步截屏、问视觉模型、执行动作、复核, 直到完成。

    task: 要在屏幕上完成的任务描述; target_hint: 目标窗口标题词(每步截屏前先置前防遮挡)。
    返回口语化结果, 永不抛异常。
    """
    if not task:
        return "（请告诉我要在屏幕上做什么。）"
    try:
        history, executed = [], 0
        repeat_sigs, verify_fails, done_rejects, early_fail_retries = [], 0, 0, 0
        last_shot, last_thought = "", ""
        sw, sh = _screen_size()
        shot_w, shot_h = _screenshot_dims(sw, sh)

        for step in range(1, max_steps + 1):
            # 0) 前台保障: 目标窗口被遮挡先置前再截屏(失败静默)
            if target_hint:
                _front_target(target_hint)

            # 1) 感知: 截屏 + UIA 控件树(坐标参照系)
            shot = screenshot()
            if not shot.get("ok"):
                return "（截图失败：%s）" % shot.get("error", "")
            shot_b64 = shot["image_base64"]
            last_shot = shot_b64
            try:
                controls = _gui_controls(target_hint)
            except Exception:
                controls = []

            # 2) 思考: 问视觉模型下一步动作
            prompt = "当前任务：%s。这是第 %d 步（上限 %d 步）。" % (task, step, max_steps)
            if history:
                prompt += "已执行的动作历史：%s。" % "；".join(history[-6:])
            if controls:
                prompt += ("屏幕上的可操作控件（来自无障碍元素树，坐标为屏幕物理像素，"
                           "点击时优先对齐这些控件）：%s。" % _format_controls(controls))
            prompt += "请结合当前截图判断任务是否已完成，返回下一步动作 JSON。"
            try:
                raw = _ask_vlm(shot_b64, prompt, system=_GUI_SYSTEM)
            except Exception as exc:
                return "（视觉模型暂时不可用，请稍后再试。%s）" % exc

            action = _parse_action(raw)
            if action is None:
                # 非法 JSON: 原 prompt 重试一次, 仍失败换降级模型最后尝试
                try:
                    raw = _ask_vlm(shot_b64, prompt + " 上次回复不是合法 JSON，请只返回一个 JSON 对象。", system=_GUI_SYSTEM)
                except Exception:
                    raw = ""
                action = _parse_action(raw)
                if action is None:
                    try:
                        base, key, model, _ = _vision_config()
                        raw = _ask_vlm_once(shot_b64, prompt + " 只返回一个合法 JSON 对象，不要任何其他文字、不要 markdown 代码块。",
                                            _GUI_SYSTEM, base, key, _VLM_FALLBACK_MODEL, {})
                        action = _parse_action(raw)
                    except Exception:
                        pass
                if action is None:
                    return "（视觉模块连续多次未能给出有效指令，已停止。）"

            thought = str(action.get("thought", ""))
            last_thought = thought
            print("[gui] 第 %d 步：%s | %s" % (step, action["action"], thought))

            # 3) 终态: done 必须先经复核才生效, 防谎报完成
            if action["action"] == "done":
                ok, why = _verify(shot_b64, "任务目标是「%s」。请只看这张截图判断：该目标是否已经在屏幕上真正完成？" % task)
                if ok is False and done_rejects < 2:
                    done_rejects += 1
                    print(f"[gui] 第{step}步 done 复核未通过({why})，继续执行（{done_rejects}/2）")
                    history.append("第%d步 系统复核：任务尚未真正完成（%s），请继续未完成的部分" % (step, (why or "目标未达成")[:40]))
                    time.sleep(1.0)
                    continue
                summary = thought or "任务已完成。"
                print(f"[gui] 任务完成（复核通过）：{summary}")
                return summary

            # 4) 早退 fail: 目标应用缺失/无法完成
            if action["action"] == "fail":
                reason = thought or "视觉模块判断无法完成。"
                # 兜底: 开放问答不敢给动作时, 换定向问法直接要"该点哪个元素+坐标",
                # 拿到坐标就合成点击——glm-4v 给不出完整动作JSON, 但能答"播放按钮在哪"
                loc = None
                if executed == 0 and early_fail_retries < 2:
                    early_fail_retries += 1
                    try:
                        loc = _locate_click(shot_b64, task, shot_w, shot_h)
                    except Exception:
                        loc = None
                if loc:
                    _log.info("第%d步早退 fail（%s），定向定位兜底→(%d,%d)", step, reason, loc['x'], loc['y'])
                    action = loc
                    thought = loc["thought"]
                elif executed == 0 and early_fail_retries < 2:
                    print(f"[gui] 第{step}步早退 fail（{reason}），宽限为等待重看（{early_fail_retries}/2）")
                    history.append("第%d步 视觉判断「%s」但尚未尝试，继续观察" % (step, reason[:30]))
                    time.sleep(1.0)
                    continue
                else:
                    print(f"[gui] 任务失败（第{step}步）：{reason}")
                    return _join_zh("任务失败", reason, _describe_screen(last_shot))

            # 5) 执行动作(FAILSAFE 抛异常即中止)
            try:
                _do_gui_action(action, shot_w, shot_h, controls)
            except _GuiFailsafe:
                print("[gui] FAILSAFE 触发，安全中止")
                return "（安全中止：你把鼠标移到了屏幕角落，我停手了。）"

            desc = action["action"]
            if action.get("text"):
                desc += "「%s」" % action["text"]
            elif action.get("keys"):
                desc += "「%s」" % action["keys"]
            history.append("第%d步 %s" % (step, desc))
            if action["action"] != "wait":
                executed += 1

            # 6) 死循环检测: 同一动作连续重复 3 次换路强提示, 4 次判失败
            sig = (action["action"], action.get("x"), action.get("y"),
                   action.get("text"), action.get("keys"))
            repeat_sigs.append(sig)
            if len(repeat_sigs) >= 3 and len(set(repeat_sigs[-3:])) == 1:
                if len(repeat_sigs) >= 4 and len(set(repeat_sigs[-4:])) == 1:
                    print("[gui] 同一动作连续重复 4 次无效，判定失败")
                    return "（同一操作重复多次均无效（界面无变化），任务目标可能不存在或需要先登录）"
                history.append("警告：同一操作已连续3次且界面无变化，下一步必须换完全不同的策略（滚动页面、换其他入口、或直接 fail 并说明真实原因）")

            # 7) 复核: 动作携带 expect 时重新截屏问 VLM 是否生效; 未生效换策略, 连续2次判失败
            time.sleep(1.0)  # 等界面响应
            expect = str(action.get("expect", "")).strip()
            if action["action"] != "wait" and expect:
                try:
                    # 复核前先置前目标窗口——否则截到的是抢前台的其他窗口(浏览器/弹窗),
                    # VLM 会老实说"没看到", 误判失败
                    if target_hint:
                        try:
                            _front_target(target_hint)
                            time.sleep(0.3)
                        except Exception:
                            pass
                    # 廉价复核优先: type 动作直接读 UIA 输入框内容是否已含输入文字(无需截图+VLM)
                    cheap_ok = False
                    if action["action"] == "type":
                        try:
                            tval = str(action.get("text", "")).strip()
                            if tval:
                                for _c in _gui_controls(target_hint):
                                    if tval in _c.get("value", "") or tval in _c.get("name", ""):
                                        cheap_ok = True
                                        break
                        except Exception:
                            pass
                    if cheap_ok:
                        ok, why = True, "UIA 确认输入框已含输入文字"
                        print(f"[gui] 第{step}步 UIA 廉价复核通过（输入框已含文字）")
                    else:
                        check_shot = screenshot()
                        if not check_shot.get("ok"):
                            check_shot = ""
                        else:
                            check_shot = check_shot["image_base64"]
                            ok, why = _verify(check_shot, "刚执行的动作是「%s」，预期屏幕上会出现：%s。请看这张截图判断：预期的效果是否已经出现？" % (desc, expect))
                            if ok is False:
                                time.sleep(1.5)
                                check_shot2 = screenshot().get("image_base64", "")
                                if check_shot2:
                                    ok2, why2 = _verify(check_shot2, "刚执行的动作是「%s」，预期屏幕上会出现：%s。请看这张截图判断：预期的效果是否已经出现？" % (desc, expect))
                                    if ok2 is not False:
                                        ok, why = ok2, why2
                    if ok is False:
                        verify_fails += 1
                        print(f"[gui] 第{step}步复核未生效（期望：{expect[:30]}；实际：{why or '未出现'}）（连续{verify_fails}次）")
                        if verify_fails >= 2:
                            return "（连续两次操作未产生预期效果（期望：%s），界面可能未响应或目标不存在）" % expect[:40]
                        history.append("警告：第%d步操作未生效（期望「%s」未出现，实际：%s），下一步必须换完全不同的做法" % (step, expect[:30], (why or "未出现")[:30]))
                    else:
                        verify_fails = 0
                except Exception:
                    pass

        # 步数耗尽: 超限话术 + 最后判断 + 屏幕状态
        return _join_zh("任务步数超出安全上限（%d 步）" % max_steps,
                        ("停顿时最后一步的判断是：%s" % last_thought) if last_thought else "",
                        _describe_screen(last_shot), "已完成的部分请您检查")
    except _GuiFailsafe:
        return "（安全中止：你把鼠标移到了屏幕角落，我停手了。）"
    except Exception as exc:
        print(f"[gui] 未预期异常：{exc}")
        return "（执行过程中出现异常：%s）" % exc


def mouse_action(action="move", x=-1, y=-1, text=""):
    """直接控制 Windows 鼠标/键盘。action: move 移动 / left_click 左键单击 / double_click 双击 /
    right_click 右键 / scroll 滚动(text=up/down) / type 输入文字(支持中文) / key 按键(如 enter、ctrl+s)。"""
    try:
        act = (action or "").lower()
        if act in ("left_click", "double_click", "right_click", "move"):
            out = _run_gui_helper(["-Action", "mouse", "-X", str(int(x)), "-Y", str(int(y)), "-Keys", act], timeout=20)
            if out == "ABORT":
                return {"ok": False, "error": "FAILSAFE 触发"}
            return {"ok": True, "msg": f"已{act} @({int(x)},{int(y)})"}
        if act == "scroll":
            out = _run_gui_helper(["-Action", "scroll", "-X", str(int(x)), "-Y", str(int(y)), "-Dir", text or "down"], timeout=20)
            if out == "ABORT":
                return {"ok": False, "error": "FAILSAFE 触发"}
            return {"ok": True, "msg": f"已滚动 {text or 'down'}"}
        if act == "type":
            import base64 as _b64
            tb = _b64.b64encode(str(text).encode("utf-8")).decode("ascii")
            out = _run_gui_helper(["-Action", "type", "-TextB64", tb], timeout=20)
            if out == "ABORT":
                return {"ok": False, "error": "FAILSAFE 触发"}
            return {"ok": True, "msg": f"已输入：{str(text)[:50]}"}
        if act == "key":
            out = _run_gui_helper(["-Action", "key", "-Keys", str(text).strip() or "enter"], timeout=20)
            if out == "ABORT":
                return {"ok": False, "error": "FAILSAFE 触发"}
            return {"ok": True, "msg": f"已按键：{text}"}
        return {"ok": False, "error": f"未知动作：{action}"}
    except Exception as e:
        return {"ok": False, "error": f"鼠标操作失败：{e}"}


# 媒体键虚拟键码(参考 Nolan hands.py _MEDIA_ACTIONS)
_MEDIA_KEYS = {
    "play_pause": 0xB3,   # VK_MEDIA_PLAY_PAUSE
    "next": 0xB0,         # VK_MEDIA_NEXT_TRACK
    "previous": 0xB1,     # VK_MEDIA_PREV_TRACK
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}

# WM_APPCOMMAND 的 APPCOMMAND 码(直发窗口消息, 比全局媒体键更可靠:
# 不需要焦点、不需要已注册的媒体会话, 实测网易云无会话时也能强制开始播放)
_WM_APPCOMMAND = 0x0319
_APPCOMMAND = {
    "play": 46,        # APPCOMMAND_MEDIA_PLAY 强制播放(不是切换)
    "play_pause": 14,  # APPCOMMAND_MEDIA_PLAY_PAUSE 切换
    "next": 11,        # APPCOMMAND_MEDIA_NEXTTRACK
    "previous": 12,    # APPCOMMAND_MEDIA_PREVIOUSTRACK
    "volume_up": 10,
    "volume_down": 9,
    "mute": 8,
}


def _find_proc_hwnd(proc: str):
    """按进程名找首个可见顶层窗口句柄, 找不到返回 0。"""
    import ctypes
    user32 = ctypes.windll.user32
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"Get-Process -Name {proc} -ErrorAction SilentlyContinue | "
             "Select-Object Id | ConvertTo-Json -Compress"],
            capture_output=True, timeout=15)
        raw = out.stdout.decode("utf-8", "replace") or "[]"
        ids = json.loads(raw)
        if not isinstance(ids, list):
            ids = [ids]
        pid_set = {p.get("Id") for p in ids}
    except Exception:
        return 0
    hit = [0]

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_int()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pid_set:
            hit[0] = hwnd
            return False
        return True
    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    try:
        user32.EnumWindows(ENUMPROC(cb), 0)
    except Exception:
        pass
    return hit[0]


def _appcommand(hwnd, action: str) -> bool:
    """向窗口直发 WM_APPCOMMAND 媒体命令。返回是否投递成功。"""
    import ctypes
    cmd = _APPCOMMAND.get(action)
    if not cmd or not hwnd:
        return False
    try:
        r = ctypes.windll.user32.PostMessageW(
            ctypes.c_void_p(hwnd), _WM_APPCOMMAND, 0, cmd << 16)
        return bool(r)
    except Exception:
        return False


def _proc_cpu_delta(proc: str, seconds: float = 3.0) -> float:
    """测量目标进程在 seconds 秒内的 CPU 累计增量(秒)。进程不存在返回 -1。"""
    ps = ("Get-Process -Name {0} -ErrorAction SilentlyContinue | "
          "Select-Object Id,CPU | ConvertTo-Json -Compress").format(proc)

    def _snap():
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=30)
        try:
            d = json.loads(r.stdout.decode("utf-8", "replace"))
            if not isinstance(d, list):
                d = [d]
            return {p.get("Id"): float(p.get("CPU", 0)) for p in d}
        except Exception:
            return {}

    s1 = _snap()
    if not s1:
        return -1.0
    time.sleep(seconds)
    s2 = _snap()
    total = 0.0
    for pid, cpu in s2.items():
        total += max(0.0, cpu - s1.get(pid, cpu))
    return total


_SMTC_CHECK_PS = r"""
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime]
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
                       $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $mgrOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()
    $mgr = Await $mgrOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $sessions = @($mgr.GetSessions())
    Write-Output ("SESSIONS=" + $sessions.Count)
    foreach ($s in $sessions) {
        $status = $s.GetPlaybackInfo().PlaybackStatus
        Write-Output ("APP={0} STATUS={1}" -f $s.SourceAppUserModelId, $status)
    }
} catch {
    Write-Output ("ERR: " + $_.Exception.Message)
}
"""


def _smtc_playing() -> str:
    """查 Windows SMTC(系统媒体会话)里网易云的真实播放状态。
    返回 "playing" / "paused" / "none"(无会话=从未真正播出过) / "unknown"。"""
    try:
        import uuid as _uuid
        ps_path = os.path.join(os.environ.get("TEMP", "."), f"smtc_{_uuid.uuid4().hex[:8]}.ps1")
        with open(ps_path, "w", encoding="utf-8-sig") as f:
            f.write(_SMTC_CHECK_PS)
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", ps_path], capture_output=True, timeout=20)
        try:
            os.remove(ps_path)
        except Exception:
            pass
        out = (r.stdout or b"").decode("utf-8", "replace")
        if "ERR:" in out or "SESSIONS=0" in out:
            return "none" if "SESSIONS=0" in out else "unknown"
        for line in out.splitlines():
            if line.startswith("APP=") and "cloudmusic" in line.lower():
                return "playing" if "PLAYING" in line else "paused"
        return "none"
    except Exception:
        return "unknown"


def _audio_audible(seconds: float = 1.5):
    """录扬声器实际输出(WASAPI loopback), 判断是否真有声音出来。
    这是终极真话源——界面动画/CPU/标题都可能骗人, 扬声器不会。
    返回 True有声 / False静音 / None(检测不可用)。"""
    try:
        import numpy as np
        import soundcard as sc
        spk = sc.default_speaker()
        mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
        with mic.recorder(samplerate=44100) as rec:
            audio = rec.record(numframes=int(seconds * 44100))
        peak = float(np.abs(audio).max())
        return peak > 0.01
    except Exception:
        return None


def _system_volume():
    """查系统主音量。返回 (音量百分比, 是否静音), 失败返回 (-1, False)。"""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()  # soundcard 录音后线程 COM 可能未初始化
        except Exception:
            pass
        from pycaw.pycaw import AudioUtilities
        ev = AudioUtilities.GetSpeakers().EndpointVolume
        return round(ev.GetMasterVolumeLevelScalar() * 100), bool(ev.GetMute())
    except Exception:
        return -1, False


def _proc_window_title(proc: str) -> str:
    """取目标进程首个可见窗口的标题, 取不到返回空串。"""
    import ctypes
    user32 = ctypes.windll.user32
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"Get-Process -Name {proc} -ErrorAction SilentlyContinue | "
             "Select-Object Id | ConvertTo-Json -Compress"],
            capture_output=True, timeout=15)
        raw = out.stdout.decode("utf-8", "replace") or "[]"
        ids = json.loads(raw)
        if not isinstance(ids, list):
            ids = [ids]
        pid_set = {p.get("Id") for p in ids}
    except Exception:
        return ""
    hit = [""]

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_int()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pid_set:
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                sb = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, sb, n + 1)
                hit[0] = sb.value
                return False
        return True
    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    try:
        user32.EnumWindows(ENUMPROC(cb), 0)
    except Exception:
        pass
    return hit[0]


def _playback_state(proc: str = "cloudmusic") -> str:
    """综合判定真实播放状态: playing(扬声器有声) / silent(有歌但无声) / none(没加载歌)。
    终极信号是 loopback 录扬声器——其他信号(CPU/标题/SMTC)都可能骗人。"""
    audible = _audio_audible()
    if audible is True:
        return "playing"
    title = _proc_window_title(proc)
    loaded = bool(title) and "网易云" not in title and "音乐" not in title
    return "silent" if loaded else "none"


def media_control(action="play_pause"):
    """系统媒体控制: 播放/暂停/切歌/音量。
    网易云不吃 WM_APPCOMMAND，主用全局媒体键(keybd_event)，兼容后台控制。
    先把网易云置前提高命中率，再发全局键。不验证状态(网易云不注册 SMTC)。
    action: play_pause / next / previous / volume_up / volume_down / mute"""
    act = (action or "").strip().lower()
    if act == "pause":
        act = "play_pause"
    if act not in _MEDIA_KEYS:
        return {"ok": False,
                "error": "支持的动作: play_pause/next/previous/volume_up/volume_down/mute"}
    try:
        hwnd = _find_proc_hwnd("cloudmusic")
        if hwnd:
            # 置前（参考 Nolan _bring_window_front）
            import ctypes
            user32 = ctypes.windll.user32
            fore = user32.GetForegroundWindow()
            fore_tid = user32.GetWindowThreadProcessId(fore, None) if fore else 0
            cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = False
            if fore_tid and fore_tid != cur_tid:
                attached = bool(user32.AttachThreadInput(cur_tid, fore_tid, True))
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(cur_tid, fore_tid, False)
            time.sleep(0.2)

        # 主路径：全局媒体键（NetEase 必吃这个）
        import ctypes
        keybd = ctypes.windll.user32.keybd_event
        vk = _MEDIA_KEYS[act]
        keybd(vk, 0, 0, 0)
        keybd(vk, 0, 2, 0)

        # 辅助：再发一次 WM_APPCOMMAND 给窗口（不依赖它）
        if hwnd:
            _appcommand(hwnd, act)

        # 友好提示文案
        msg_map = {
            "play_pause": "暂停播放",
            "next": "播放下一首歌",
            "previous": "播放上一首歌",
            "volume_up": "已调高音量",
            "volume_down": "已调低音量",
            "mute": "已切换静音",
        }
        return {"ok": True, "msg": msg_map.get(act, f"已执行{act}")}
    except Exception as e:
        return {"ok": False, "error": f"媒体控制失败：{e}"}


def play_specific_song(query: str, app="网易云音乐"):
    """搜索并播放指定歌曲: query 如 "周杰伦 晴天" 或 "稻香"。
    1) 找搜索框(编辑框) -> ValuePattern 写关键词 -> 回车
    2) 等结果渲染 -> 找结果区第一个 play 按钮(控件类型 Button, 名含 play, y<600) -> Invoke
    3) loopback 验证出声
    返回 {"ok": True, "msg": ...} 或 {"ok": False, "error": ...}。"""
    from . import uia as _uia
    proc = _APP_PROC.get(app, "cloudmusic")
    try:
        hwnd = _find_proc_hwnd(proc)
        if not hwnd:
            from .apps import open_app
            open_app(name=app)
            for _ in range(10):
                time.sleep(1.5)
                hwnd = _find_proc_hwnd(proc)
                if hwnd:
                    break
        if not hwnd:
            return {"ok": False, "error": f"没能打开或找到{app}的窗口"}

        # 置前
        import ctypes
        user32 = ctypes.windll.user32
        fore = user32.GetForegroundWindow()
        fore_tid = user32.GetWindowThreadProcessId(fore, None) if fore else 0
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = False
        if fore_tid and fore_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, fore_tid, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur_tid, fore_tid, False)
        time.sleep(0.3)

        # 1) 搜索框写关键词
        # 网易云搜索框名会随当前歌手变(如 "孙燕姿" "同类 - 孙燕姿")，按类型 Edit 找
        ok = _uia.set_edit_value(hwnd, "", query)
        if not ok:
            # 放歌后网易云常切到「正在播放」全屏页, 该页没有搜索框:
            # 先按 Esc 退出全屏回到主界面, 再重试一次
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            time.sleep(0.2)
            ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)   # Esc down
            ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)   # Esc up
            time.sleep(0.8)
            ok = _uia.set_edit_value(hwnd, "", query)
        if not ok:
            return {"ok": False, "error": "找不到搜索框"}
        time.sleep(0.3)
        # 回车
        ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x0D, 0, 2, 0)

        # 2) 等结果渲染
        time.sleep(2.5)

        # 3) 结果区找第一个 play 按钮(y<600 避开底部主播放栏)
        invoked = _uia.find_element_by_type_and_name(hwnd, 50000, "play", max_y=600)
        if not invoked:
            # 兜底：找任意名含 play 的按钮(结果区通常都叫 play)
            invoked = _uia.invoke_element_by_name(hwnd, "play", min_y=0)
        if not invoked:
            return {"ok": False, "error": "搜索结果里没找到播放按钮"}

        time.sleep(2.5)
        if _playback_state(proc) == "playing":
            return {"ok": True, "msg": f"正在播放：{query}"}

        state = _playback_state(proc)
        vol, muted = _system_volume()
        volinfo = f"系统音量{vol}%{'，已静音' if muted else ''}" if vol >= 0 else "系统音量未知"
        if state == "silent":
            return {"ok": False,
                    "error": f"点击了播放但扬声器无声（{volinfo}）"}
        return {"ok": False, "error": "播放失败，请重试"}
    except Exception as e:
        return {"ok": False, "error": f"点歌失败：{e}"}


def play_music(app="网易云音乐"):
    """随机播放音乐: UIA InvokePattern 直接触发主播放器的「play」按钮
    (参考 Nolan uia.py; 实测鼠标点坐标不可靠, Invoke 编程触发才有效)。
    点击后用 loopback 录扬声器验证真的出声。找不到按钮时回退 WM_APPCOMMAND。
    返回 {"ok": True, "msg": ...} 或 {"ok": False, "error": ...}。"""
    from . import uia as _uia
    proc = _APP_PROC.get(app, "cloudmusic")
    try:
        hwnd = _find_proc_hwnd(proc)
        if not hwnd:
            from .apps import open_app
            open_app(name=app)
            for _ in range(10):
                time.sleep(1.5)
                hwnd = _find_proc_hwnd(proc)
                if hwnd:
                    break
        if not hwnd:
            return {"ok": False, "error": f"没能打开或找到{app}的窗口"}

        # 主路径: InvokePattern 直接触发底部主播放键(菜单项「play」, y>600)
        invoked = _uia.invoke_element_by_name(hwnd, "play", min_y=600)
        if invoked:
            time.sleep(2.5)
            if _playback_state(proc) == "playing":
                return {"ok": True, "msg": "音乐已在播放"}

        # 兜底1: WM_APPCOMMAND 强制播放
        if _appcommand(hwnd, "play"):
            time.sleep(2.0)
            if _playback_state(proc) == "playing":
                return {"ok": True, "msg": "音乐已在播放"}

        # 兜底2: 全窗口任意名为 play 的控件再试一次 Invoke
        if _uia.invoke_element_by_name(hwnd, "play"):
            time.sleep(2.5)
            if _playback_state(proc) == "playing":
                return {"ok": True, "msg": "音乐已在播放"}

        state = _playback_state(proc)
        vol, muted = _system_volume()
        volinfo = f"系统音量{vol}%{'，已静音' if muted else ''}" if vol >= 0 else "系统音量未知"
        if state == "silent":
            return {"ok": False,
                    "error": f"触发了播放但扬声器没有声音（{volinfo}）。"
                             "可能是暂停状态或应用内音量为0，请手动看一眼网易云"}
        return {"ok": False,
                "error": f"没找到播放按钮且强制播放无效（{volinfo}）。"
                         "请先确认已登录，再手动双击一首歌"}
    except Exception as e:
        return {"ok": False, "error": f"播放音乐失败：{e}"}


def get_controls(window=""):
    """枚举 Windows 前台(或指定标题窗口)的可交互控件树(UIA)，返回每个控件的名称/类型/中心坐标。"""
    try:
        cs = _gui_controls(window)
        items = []
        for c in cs:
            rx, ry, w, h = c["rect"]
            items.append({
                "name": c.get("name", ""), "type": c.get("type", ""),
                "x": rx + w // 2, "y": ry + h // 2,
                "rect": c["rect"], "enabled": c.get("enabled", True),
            })
        return {"ok": True, "count": len(items), "controls": items}
    except Exception as e:
        return {"ok": False, "error": f"控件枚举失败：{e}"}