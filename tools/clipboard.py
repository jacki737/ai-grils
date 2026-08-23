"""Windows 剪贴板读写(经临时文件传中文, 避免引号转义)

get 用 Get-Clipboard -Raw 读; set 先把内容写进 UTF-8 临时文件, 再让 PowerShell
读文件塞进剪贴板。用文件中转的原因: 中文/引号直接拼进 powershell.exe -Command
字符串极易被转义搞坏, 走文件最稳。
"""
import os
import subprocess
import uuid

from .screen import _win_temp_paths


def clipboard(action: str = "get", text: str = ""):
    """读写 Windows 剪贴板: clipboard('get') 读取; clipboard('set', text='内容') 写入

    参数:
      action: "get" 读取剪贴板内容 / "set" 写入指定内容
      text:   set 时要写入的文本
    返回: {"ok": True, "text": 读到的内容} 或 {"ok": True, "msg": ...} 或错误。
    """
    action = (action or "").lower()
    try:
        if action == "get":
            p = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                capture_output=True, timeout=15,
            )
            val = (p.stdout or b"").decode("utf-8", "replace").strip()
            return {"ok": True, "text": val[:2000] or "(剪贴板为空)"}
        if action == "set":
            # 经临时文件传递, 避免命令引号转义地狱
            fname = "clip_" + uuid.uuid4().hex[:8] + ".txt"
            win_path, wsl_path = _win_temp_paths(fname)
            with open(wsl_path, "w", encoding="utf-8") as f:
                f.write(text or "")
            ps = "Set-Clipboard -Value ([System.IO.File]::ReadAllText('" + win_path + "', [System.Text.Encoding]::UTF8))"
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=15,
            )
            try:
                os.remove(wsl_path)
            except Exception:
                pass
            return {"ok": True, "msg": "已写入剪贴板"}
        return {"ok": False, "error": f"未知动作: {action}(仅 get/set)"}
    except Exception as e:
        return {"ok": False, "error": f"剪贴板操作失败: {e}"}