"""文件读写(限 home 目录, 禁系统关键路径)

read_file 随便读(仍限制体积防撑爆回复); write_file 只允许写 home 和 /tmp,
系统目录、Windows 系统目录、hosts 一律拒绝。同 run_shell 一样是安全敏感工具。
"""
import os
import re

from .safety import BLOCKED_PATHS, WINDOWS_HOSTS_RE, ALLOWED_HOME


def read_file(path: str):
    """读取文本文件(限制 200KB, 返回前 8000 字符)

    参数: path 可以是绝对路径或 ~ 开头的路径。
    返回: {"ok": True, "path": 规范化路径, "content": 内容} 或错误 dict。
    """
    try:
        p = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(p):
            return {"ok": False, "error": f"文件不存在: {path}"}
        if os.path.getsize(p) > 200 * 1024:
            return {"ok": False, "error": f"文件太大({os.path.getsize(p)} bytes), 超过 200KB 限制"}
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"ok": True, "path": p, "content": content[:8000]}
    except Exception as e:
        return {"ok": False, "error": f"读取失败: {e}"}


def write_file(path: str, content: str):
    """写入文本文件(新建或覆盖), 只允许写 home 和 /tmp

    安全要点(按顺序):
      1) realpath 解开符号链接, 防止借软链把内容写进系统文件;
      2) 系统关键目录 / Windows 系统目录 / hosts 一律拒绝;
      3) 白名单目录检查: 只有 ~、/tmp、ai-girlfriend 项目目录允许落盘。
    参数: path 目标文件路径, content 完整文件内容(覆盖写入)。
    """
    try:
        p = os.path.abspath(os.path.expanduser(path))
        # 反符号链接, 防止通过软链写系统文件
        p = os.path.realpath(p)
        # 系统关键目录与 Windows hosts 一律拒绝
        if p.lower().startswith(BLOCKED_PATHS):
            return {"ok": False, "error": f"禁止写系统目录: {path}"}
        if re.search(r"/mnt/[a-z]/(?:Windows|Program Files|ProgramData)", p, re.IGNORECASE):
            return {"ok": False, "error": f"禁止写 Windows 系统目录: {path}"}
        if WINDOWS_HOSTS_RE.search(p):
            return {"ok": False, "error": f"禁止修改 Windows hosts 等关键文件: {path}"}
        # 只允许写 home 和 /tmp 下的文件(防止乱写系统)
        if not (p == ALLOWED_HOME or p.startswith(ALLOWED_HOME + "/")
                or p == "/tmp" or p.startswith("/tmp/")
                or p == "/home/marka/ai-girlfriend" or p.startswith("/home/marka/ai-girlfriend/")):
            return {"ok": False, "error": f"禁止写系统目录, 只允许写 home 下文件: {path}"}
        # 目标目录不存在时先自动创建(不存在的父目录用 exist_ok 静默忽略)
        os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(p) else None
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return {"ok": True, "path": p, "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": f"写入失败: {e}"}