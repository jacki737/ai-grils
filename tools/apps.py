"""打开 Windows 软件: 系统命令/路径直达 + 注册表/开始菜单/常见目录全盘查找

核心思路: 不硬编码任何软件路径(换机器就失效), 而是分级降级:
  ①系统自带命令(notepad/calc...)直接 cmd start;
  ②给的如果是路径(/mnt/c/...、C:\\...、xxx.exe)就原样启动;
  ③其他一律交给 static/open_app_helper.ps1 去注册表/开始菜单/常见目录自动找,
    找到就启动并确认窗口真的出现(返回 OK:/RUNNING:/FAIL 前缀)。
英文/俗称名(wechat)自动映射到中文显示名(微信), 避免搜英文找不到中文装的软件。
"""
import os
import re
import shlex
import subprocess

from ._paths import STATIC_DIR

# Windows 系统自带命令/别名: 任何机器都能直接启动(不依赖具体安装路径)
BUILTIN_CMDS = {
    "notepad": "notepad", "记事本": "notepad",
    "calc": "calc", "计算器": "calc",
    "explorer": "explorer", "资源管理器": "explorer",
    "mspaint": "mspaint", "画图": "mspaint",
    "winver": "winver", "cmd": "cmd", "命令提示符": "cmd",
    "powershell": "powershell", "taskmgr": "taskmgr", "任务管理器": "taskmgr",
    "control": "control", "控制面板": "control",
    "regedit": "regedit", "注册表编辑器": "regedit",
}

# 其他软件一律交给 open_app_helper.ps1 自动查找:
#   注册表 App Paths → 卸载表 → 开始菜单 → 常见安装目录(注册了就能找到, 换机器也不怕)
# 英文/俗称 → 中文显示名(纯名字映射, 不依赖路径, 换机器照用)
APP_ALIASES = {
    "wechat": "微信", "weixin": "微信",
    "chrome": "Google Chrome", "google chrome": "Google Chrome",
    "谷歌": "Google Chrome", "谷歌浏览器": "Google Chrome",
    "edge": "Microsoft Edge", "browser": "Microsoft Edge", "浏览器": "Microsoft Edge",
    "pycharm": "PyCharm",
    "qqmusic": "QQ音乐", "qq音乐": "QQ音乐",
    "netease": "网易云音乐", "网易云音乐": "网易云音乐", "cloudmusic": "网易云音乐",
    "网易": "网易云音乐", "网易云": "网易云音乐", "云音乐": "网易云音乐", "音乐": "网易云音乐",
    "obsidian": "Obsidian", "typora": "Typora",
    "今日头条": "今日头条", "头条": "今日头条", "toutiao": "今日头条",
}

# 口语后缀/词缀: 归一化名字时剥离("网易云音乐软件" -> "网易云音乐")
_APP_SUFFIXES = [
    "应用程序", "客户端", "电脑版", "浏览器", "软件", "应用", "程序", "助手",
    "app", "application",
]
_APP_PUNCT = "。！？!?.，,、 "


def _normalize_app_name(name: str) -> str:
    """归一化软件名: 剥口语后缀(软件/浏览器/客户端...)与尾标点, 去空格, 小写。

    例如: "网易云音乐软件！" -> "网易云音乐"。剥到不能再剥为止(while 循环),
    比如 "QQ音乐客户端软件" 会依次剥掉 "软件" 再剥 "客户端"。
    """
    s = (name or "").strip()
    while True:
        changed = False
        if s and s[-1] in _APP_PUNCT:
            s = s[:-1]
            changed = True
        for suf in _APP_SUFFIXES:
            if s.lower().endswith(suf.lower()) and len(s) > len(suf):
                s = s[:-len(suf)]
                changed = True
        if not changed:
            break
    return s.replace(" ", "").lower()


def _resolve_alias(term: str) -> str:
    """别名解析: 精确命中 -> 双向子串(长键优先)。没命中原样返回, 不猜测。

    顺序:
      1) term 整体在 APP_ALIASES 里(如 wechat) -> 直接取中文名;
      2) term 包含某个别名(如 "打开wechat" 归一后仍是 wechat) -> 取该别名对应名,
         长键优先避免短键误伤("音乐"先查 "网易云音乐" 而不是被 "音乐" 抢);
      3) 某个别名包含 term(如 term="微" 但键 "微信" 里含"微") -> 反向子串命中;
      4) 都不中 -> 原样返回, 交给 helper 的注册表/开始菜单查找, 不瞎猜。
    """
    term = (term or "").strip()
    if not term:
        return term
    t = term.lower()
    if t in APP_ALIASES:
        return APP_ALIASES[t]
    for k in sorted(APP_ALIASES, key=len, reverse=True):
        if len(k) >= 2 and k in t:
            return APP_ALIASES[k]
    if len(t) >= 2:
        for k in sorted(APP_ALIASES, key=len):
            if len(k) >= 2 and t in k:
                return APP_ALIASES[k]
    return term


def open_app(name: str, args: str = ""):
    """打开 Windows 软件(自动识别, 不依赖硬编码路径)

    查找顺序(见模块注释):
      1) 系统自带命令(notepad/calc/explorer...) → cmd start, 任何机器可用;
      2) name 是文件路径(/mnt/c/... 或 C:\\... 或 xxx.exe) → 直接启动;
      3) 其他 → PowerShell 助手按 注册表/开始菜单/常见目录 全盘查找, 装了就能开。
    英文名自动翻译成中文显示名(wechat→微信), 避免搜英文找不到中文装的软件。

    参数:
      name: 软件名或路径, 如 "微信" / "wechat" / "chrome" / "C:\\Tools\\x.exe"
      args: 额外启动参数, 如 chrome 打开指定网址 "https://baidu.com"
    返回: {"ok": True, "msg": ...} 或 {"ok": False, "error": 诚实失败原因}
    """
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "软件名为空"}
    base = name.lower()
    if base.endswith(".exe"):
        base = base[:-4]
    argv = shlex.split(args) if args else []
    try:
        # 1) 系统自带命令 → cmd start(跨机器可用)
        cmd_target = BUILTIN_CMDS.get(base) or BUILTIN_CMDS.get(name)
        if cmd_target:
            cmdargs = ["cmd.exe", "/c", "start", "", cmd_target] + argv
            subprocess.Popen(cmdargs, shell=False, start_new_session=True)
            return {"ok": True, "msg": f"已启动: {name} {args}"}

        # 2) 直接给的是路径 → 启动它
        if name.startswith("/mnt/"):
            # WSL 风格路径(/mnt/c/...) → 原生 Windows 上先转成 C:\... 再检查
            exe = name
            if os.name == "nt":
                m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", name)
                if m:
                    exe = m.group(1).upper() + ":\\" + m.group(2).replace("/", "\\")
            if not os.path.exists(exe):
                return {"ok": False, "error": f"路径不存在: {name}"}
            subprocess.Popen([exe] + argv, start_new_session=True)
            return {"ok": True, "msg": f"已启动: {name} {args}"}
        if "\\" in name or re.match(r"^[A-Za-z]:", name):
            # Windows 路径 → cmd start
            cmdargs = ["cmd.exe", "/c", "start", "", name] + argv
            subprocess.Popen(cmdargs, shell=False, start_new_session=True)
            return {"ok": True, "msg": f"已启动: {name} {args}"}

        # 3) 通用查找: 名字归一化(剥"软件/浏览器"等后缀) + 别名解析后,
        #    PowerShell 助手按 注册表 App Paths/卸载表/开始菜单/常见目录 全盘查找, 装了就能开
        term = _resolve_alias(_normalize_app_name(name))
        # 归一化后剥成了空/只剩前缀时, 回退原名再试(如「浏览器」本身)
        terms = [term] + ([name] if term != name else [])
        script = os.path.join(STATIC_DIR, "open_app_helper.ps1")
        for candidate in terms:
            if not os.path.exists(script):
                break
            try:
                p = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script, "-Name", candidate, "-Extra", args or ""],
                    capture_output=True, timeout=120,
                )
                # 助手的三种答复前缀:
                #   OK:     窗口真的出现了(启动成功)
                #   RUNNING:进程已在跑但没有窗口(托盘应用, 也算启动成功)
                #   其他:    没找到/启动失败
                out = (p.stdout or b"").decode("utf-8", "ignore").strip()
                if out.startswith("OK:"):
                    return {"ok": True, "msg": f"已启动: {name} {args} ({out[3:]})"}
                if out.startswith("RUNNING:"):
                    return {"ok": True, "msg": f"已启动: {name} {args} ({out[8:]})"}
            except Exception:
                pass

        return {"ok": False,
                "error": f"没在系统里找到「{name}」的安装。可以让贾维斯: 1)给完整路径打开, 2)先安装这个软件, 3)告诉我它装在哪。"}
    except Exception as e:
        return {"ok": False, "error": f"启动失败: {e}"}