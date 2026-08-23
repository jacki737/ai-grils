"""委托 Claude Code CLI 写代码(DeepSeek 后端)

write_code 是"写代码"专用工具: 把需求交给 Claude Code CLI(在 WSL 里跑),
它自己会读文件、改代码、落盘。当前 Claude Code 配置的是 DeepSeek 后端
(见 ~/.bashrc 的 ANTHROPIC_* 环境变量), 所以实际生成代码的是 DeepSeek 模型。
"""
import os
import re
import subprocess


def _read_bashrc_env():
    """从 ~/.bashrc 提取 ANTHROPIC_* 环境变量(Claude Code 用 DeepSeek 后端)

    Claude Code 通过 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY 指向第三方后端,
    这些变量写在 ~/.bashrc 里, 这里手动读出来传给 claude 子进程
    (确保在非交互 shell 里也能带上配置)。
    """
    env = {}
    try:
        for line in open(os.path.expanduser("~/.bashrc"), encoding="utf-8", errors="replace"):
            m = re.match(r"\s*export\s+(\w+)=(.*)", line.strip())
            if m and m.group(1).startswith("ANTHROPIC"):
                val = m.group(2).strip().strip('"').strip("'")
                env[m.group(1)] = val
    except Exception:
        pass
    return env


def write_code(req: str, cwd: str = None, timeout: int = 600):
    """委托 Claude Code CLI 写代码/改代码(DeepSeek 后端)

    参数:
      req:     需求描述(要做什么、改哪个文件、注意什么)
      cwd:     工作目录, 默认 /home/marka
      timeout: 超时秒数, 默认 600(写代码很慢, 给足时间)
    返回: {"ok": bool, "output": 命令输出, "exit_code": int} 或错误 dict。
    注意: 这里不额外做文件写入白名单——Claude Code 自己决定读写哪些文件。
    """
    if not req or not req.strip():
        return {"ok": False, "error": "需求为空"}
    workdir = cwd or "/home/marka"
    env = dict(os.environ)
    env.update(_read_bashrc_env())
    env.setdefault("CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT", "1")
    try:
        proc = subprocess.run(
            ["claude", "-p", req, "--permission-mode", "acceptEdits", "--output-format", "text"],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout,
        )
        out = (proc.stdout or "") + (("\n[stderr] " + proc.stderr[:1000]) if proc.stderr else "")
        return {"ok": proc.returncode == 0, "output": out[:4000] or "(无输出)", "exit_code": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Claude Code 超时(>{timeout}s)"}
    except FileNotFoundError:
        return {"ok": False, "error": "未找到 claude 命令, 请先安装 Claude Code CLI"}
    except Exception as e:
        return {"ok": False, "error": f"执行异常: {e}"}