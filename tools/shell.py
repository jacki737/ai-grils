"""执行 shell 命令(带安全检查)

模型最常用的工具之一。用 WSL 的 bash 跑命令, 所有命令先过 safety._check_shell_safety,
危险操作直接返回拦截原因, 不会真的执行。
注意这里是 WSL Linux 环境: 要操作 Windows 需用 powershell.exe/cmd.exe 前缀,
Windows 文件路径要写成 /mnt/c/... 形式。
"""
import subprocess

from .safety import _check_shell_safety


def run_shell(cmd: str, timeout: int = 60):
    """执行 shell 命令, 返回 stdout/stderr/exit_code

    参数:
      cmd:     要执行的 shell 命令(必填)
      timeout: 超时秒数, 默认 60(防止模型乱跑长命令卡死服务器)
    返回:
      {"ok": bool, "exit_code": int, "output": str} 或 {"ok": False, "error": str}
    """
    if not cmd or not cmd.strip():
        return {"ok": False, "error": "命令为空"}
    danger = _check_shell_safety(cmd)
    if danger:
        return {"ok": False, "error": danger}
    try:
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            capture_output=True, timeout=timeout,
        )
        # Windows 程序(如 powershell.exe)输出常是 GBK; 先按 UTF-8 解, 失败回退 GBK
        def dec(b):
            if not b:
                return ""
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                return b.decode("gbk", "replace")
        out = dec(proc.stdout) + (("\n[stderr] " + dec(proc.stderr)) if proc.stderr else "")
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": out[:4000] or "(无输出)",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"命令超时(>{timeout}s)"}
    except Exception as e:
        return {"ok": False, "error": f"执行异常: {e}"}