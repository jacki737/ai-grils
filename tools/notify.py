"""Windows 桌面通知: 优先 Win11 原生 Toast, 失败自动降级弹窗

内容和标题都经 UTF-8 临时文件传给 static/toast_helper.ps1(纯 ASCII 源文件,
中文必须走文件, 否则 PowerShell 源文件里带中文会乱码/报错)。
toast_helper.ps1 内部优先 Win11 原生 Toast, 系统不支持时自动降级 MessageBox 弹窗。
"""
import os
import subprocess
import uuid

from ._paths import STATIC_DIR
from .screen import _win_temp_paths


def notify(text: str, title: str = "小暖"):
    """发送 Windows 桌面通知: 优先 Win11 原生 Toast, 失败自动降级为弹窗

    参数:
      text:  通知正文(必填)
      title: 通知标题, 默认 "小暖"
    返回: {"ok": True, "msg": ...} 或错误 dict。
    """
    if not text or not text.strip():
        return {"ok": False, "error": "通知内容为空"}
    try:
        # 内容和标题各写一个 UTF-8 临时文件, toast_helper.ps1 读取后发送
        # (避免中文/引号拼进命令行被转义, 也避免 .ps1 源文件含非 ASCII 字符)
        win_txt, wsl_txt = _win_temp_paths("notif_" + uuid.uuid4().hex[:8] + ".txt")
        win_ttl, wsl_ttl = _win_temp_paths("notif_" + uuid.uuid4().hex[:8] + "_t.txt")
        with open(wsl_txt, "w", encoding="utf-8") as f:
            f.write(text[:300])
        with open(wsl_ttl, "w", encoding="utf-8") as f:
            f.write(title[:50] or "小暖")
        script = os.path.join(STATIC_DIR, "toast_helper.ps1")
        if not os.path.exists(script):
            return {"ok": False, "error": "缺少 static/toast_helper.ps1"}
        # 后台异步发送, 不阻塞本次工具调用
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", script, "-TextFile", win_txt, "-TitleFile", win_ttl],
            start_new_session=True,
        )
        # 不立即删除临时文件: PS 异步读取可能还没执行完, 留在 temp 目录由系统清理
        return {"ok": True, "msg": f"已发送桌面通知: {title}"}
    except Exception as e:
        return {"ok": False, "error": f"通知失败: {e}"}