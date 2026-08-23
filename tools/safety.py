"""shell 命令安全检查: 危险命令/系统关键路径/全盘搜索 一律拒绝

被 shell.run_shell 和 schedule.run_scheduled 共用。任何要落地的 shell 命令
都必须先过 _check_shell_safety, 返回 None 表示放行, 返回字符串表示拦截原因。
设计原则: 宁可误拦(提示用户换 open_app/search_files), 不可放跑危险操作。
"""
import os
import re

# 绝对危险操作: 一旦出现直接拒绝, 不给任何解释机会。
# 匹配的是一整条模式, 注意所有模式都经过 _normalize_cmd 归一化后再比对,
# 所以 "rm -r -f" 会被合并成 "rm -rf" 才能被命中, 防拆词绕过。
DANGEROUS_CMD = re.compile(
    r"rm\s+-[a-z]*r[a-z]*f|mkfs\.|dd\s+if=.*of=/dev|:\(\)|shutdown|reboot|halt|"
    r"format\s+[a-z]:|del\s+/[sq]|rd\s+/[sq]|diskpart|reg\s+delete|"
    r"chmod\s+-R\s+777\s+/|mv\s+.*\s+/etc|curl[^|]*\|\s*sh|wget[^|]*\|\s*sh",
    re.IGNORECASE,
)
# 系统关键路径: 任何"写"操作禁止触碰。
# 注意这是前缀匹配(如 "/etc"), 所以普通文件如 /etc 下面也会被拦——这正是目的。
BLOCKED_PATHS = ("/etc", "/boot", "/usr", "/proc", "/sys", "/dev", "/var/lib", "/root")
# Windows hosts / hosts.txt(经 /mnt/c 或盘符路径引用):
# hosts 是 Windows 网络关键文件, 改坏会导致上不了网, 单独拎出来拦截。
WINDOWS_HOSTS_RE = re.compile(
    r"/mnt/[a-z]/[^\s;|&]*hosts(?:\.txt)?|"
    r"\bhosts\.txt\b|"
    r"[A-Za-z]:[\\/][^\"'\s]*hosts|"
    r"drivers[\\/]etc[\\/]hosts",
    re.IGNORECASE,
)
# 写/破坏类动词(命中即视为"修改"); echo/cat/printf 需配合重定向才拦截。
# 用于判断命令在"读"还是"写": 只有"写"指向系统关键路径才拦, 单纯 "cat /etc/hostname"
# 这种读取是允许的。
MUTATE_VERBS_RE = re.compile(
    r"\b(rm|mv|chmod|chown|chattr|dd|mkfs|truncate|touch|install|mount|umount|tee|cp|ln|"
    r"sed\s+-i|systemctl|service|apt|apt-get|dpkg|yum|pacman)\b",
    re.IGNORECASE,
)
REDIRECT_RE = re.compile(r"\b(echo|printf|cat)\b.*(>|>>)", re.IGNORECASE)
ALLOWED_HOME = os.path.expanduser("~")


def _normalize_cmd(cmd: str) -> str:
    """折叠空白, 并把 rm -r -f 拆开写法归一成 rm -rf, 防止绕过检测

    模型给的命令格式不固定("rm -r -f"、"rm  -rf" 混着来), 先统一成最紧凑形式,
    再交给各个正则匹配, 保证"拆词写"骗不过检测。
    """
    s = re.sub(r"\s+", " ", cmd.strip())

    def merge(m):
        # 取出 "rm" 后所有 "-xxx" 短旗标, 合并成 "-rf", 其余参数原样保留
        parts = m.group(0).split()
        flags = "".join(p[1:] for p in parts[1:] if re.fullmatch(r"-[a-zA-Z]+", p))
        rest = [p for p in parts[1:] if not re.fullmatch(r"-[a-zA-Z]+", p)]
        return "rm -" + flags + (" " + " ".join(rest) if rest else "")

    return re.sub(r"\brm\b\s+(?:-[a-zA-Z]+\s+)*[^\s;|&]*", merge, s)


def _is_mutating(prefix: str) -> bool:
    """判断目标之前的命令片段是否在'写'

    用法: 拦截 "mv /x /etc" 时, 把目标路径 "/etc" 之前那段命令传给本函数,
    若里面有写动词(rm/mv/tee/echo>) 就说明是写操作, 应该拦。
    这样只读命令(如 "ls /etc")不会被误伤。
    """
    return bool(MUTATE_VERBS_RE.search(prefix) or REDIRECT_RE.search(prefix))


def _check_shell_safety(cmd: str):
    """命令安全检查主入口: 放行返回 None, 拦截返回原因字符串

    检查顺序(从重到轻):
      1) 绝对危险命令(rm -rf/mkfs/shutdown/curl|sh...) -> 直接拒;
      2) 对根目录 / 的破坏性操作 -> 直接拒;
      3) 系统关键路径(/etc /usr...) 前的写操作 -> 拒;
      4) Windows hosts 关键文件 -> 拒;
      5) Windows 系统目录(/mnt/c/Windows 等)写操作 -> 拒;
      6) 全盘 find/where/Get-ChildItem -Recurse -> 拒并指路(遍历 /mnt 9p 挂载必超时)。
    """
    norm = _normalize_cmd(cmd)
    if DANGEROUS_CMD.search(norm):
        return "命令包含危险操作(rm -rf/mkfs/shutdown等), 已拒绝执行。"
    # 根目录 / 保护: rm/mv/chmod 等直接指向根
    if re.search(r"\b(rm|mv|chmod|chown|chattr)\b.*(^|\s)/(;|$|\||&|\s)", norm):
        return "禁止对根目录 / 执行破坏性操作。"
    # 系统关键路径: 目标前出现写动词或重定向即拒绝
    for p in BLOCKED_PATHS:
        if re.search(r"(^|[\s;|&])" + re.escape(p) + r"(/|\s|;|$|\||&)", norm) and _is_mutating(norm.split(p)[0]):
            return f"禁止操作系统目录 {p}。"
    # Windows hosts: 同上
    if WINDOWS_HOSTS_RE.search(norm) and _is_mutating(norm.split("hosts")[0]):
        return "禁止修改 Windows hosts 等关键文件。"
    # Windows 系统目录: 写操作禁止
    w = re.search(r"/mnt/[a-z]/(?:Windows|Program Files|ProgramData)", norm)
    if w and _is_mutating(norm.split(w.group(0))[0]):
        return "禁止修改 Windows 系统目录。"
    # 全盘 find / where / Recurse 搜索: /mnt 9p 挂载遍历极慢, 必定超时 → 直接拒绝并指路
    if re.search(r"\bfind\s+/mnt/[a-z](\s+|$)", norm):
        return "禁止全盘 find(在 /mnt 挂载上递归会超时)。打开软件请用 open_app 工具(自动查注册表/开始菜单); 找文件用 search_files; 或指定具体子目录。"
    if re.search(r"\bwhere\s+/r\s+[A-Za-z]:\\?", norm):
        return "禁止全盘 where 搜索(会超时)。打开软件请用 open_app 工具, 找文件用 search_files。"
    if re.search(r"Get-ChildItem[^\n]*[A-Za-z]:\\[^\n]*-Recurse", norm, re.IGNORECASE):
        return "禁止 PowerShell 全盘递归搜索(会超时)。打开软件请用 open_app 工具, 找文件用 search_files。"
    return None