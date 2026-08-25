"""脚本生成工具：先探测上下文，再按需求生成可运行的 Python 脚本"""
import json
import os
import sys
from pathlib import Path

# 确保能导入同级工具
sys.path.insert(0, str(Path(__file__).parent))

from tools.sysinfo import system_info


# ── 可用探针：名字 -> 返回 dict/str 的函数 ──
def _probe_system_info():
    return system_info()


def _probe_cwd():
    return {"cwd": os.getcwd()}


def _probe_requirements():
    """读取 requirements.txt / pyproject.toml"""
    reqs = {}
    for f in ("requirements.txt", "pyproject.toml"):
        p = Path.cwd() / f
        if p.exists():
            reqs[f] = p.read_text(encoding="utf-8")[:2000]
    return reqs or {"msg": "无依赖文件"}


def _probe_git_status():
    """git status 简报"""
    try:
        import subprocess
        out = subprocess.check_output(["git", "status", "--short"], text=True, timeout=5, errors="ignore")
        return {"git_status": out.strip()[:1000]}
    except Exception as e:
        return {"git_status": f"不可用: {e}"}


_PROBES = {
    "system_info": _probe_system_info,
    "cwd": _probe_cwd,
    "requirements": _probe_requirements,
    "git_status": _probe_git_status,
}


def gen_script(probes: list[str], intent: str) -> dict:
    """
    根据真实上下文生成 Python 脚本。

    Args:
        probes: 探针名列表，可选 ["system_info", "cwd", "requirements", "git_status"]
        intent: 用户想写什么脚本的自然语言描述

    Returns:
        {"ok": True, "code": "完整可运行的 Python 代码"} 或 {"ok": False, "error": "..."}
    """
    # 1. 收集上下文
    ctx = {}
    for name in probes:
        fn = _PROBES.get(name)
        if fn:
            try:
                ctx[name] = fn()
            except Exception as e:
                ctx[name] = {"error": str(e)}

    # 2. 构造 Prompt
    prompt = f"""根据下面真实环境信息，写一个**完整可运行**的 Python 脚本。

环境信息（JSON）：
{json.dumps(ctx, ensure_ascii=False, indent=2)}

用户需求：
{intent}

===== 硬性要求 =====
1. 只输出**完整可运行代码**，不要任何解释、Markdown、注释前缀。
2. 必须包含 main() 入口，直接 `python script.py` 可运行。
3. 优先用标准库；第三方库必须在代码顶部用 try/except 导入并在缺失时给出友好提示。
4. 所有 I/O、外部调用都要有异常兜底，失败时打印友好错误并返回非零退出码。
5. Windows/Linux 双环境兼容（路径用 pathlib，编码显式指定 utf-8）。
6. 如需第三方库，在代码开头用注释标注 `# pip install xxx`。

开始输出代码："""

    # 3. 调用 LLM
    try:
        from core.brain import call_llm
        msg = call_llm([{"role": "user", "content": prompt}])
        code = (msg.get("content") or "").strip()
        # 去除可能的代码围栏
        if code.startswith("```"):
            lines = code.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            code = "\n".join(lines)
        if not code:
            return {"ok": False, "error": "模型返回空代码"}
        return {"ok": True, "code": code}
    except Exception as e:
        return {"ok": False, "error": f"生成失败: {e}"}


if __name__ == "__main__":
    # 手工测试: python -m tools.script_gen "system_info,cwd" "写个监控 CPU 内存的守护进程"
    import sys
    if len(sys.argv) >= 3:
        probes = sys.argv[1].split(",")
        intent = sys.argv[2]
    else:
        probes = ["system_info", "cwd"]
        intent = "写一个监控 CPU、内存、磁盘使用率的守护进程，每 30 秒打印一次，支持 Ctrl+C 优雅退出"
    r = gen_script(probes, intent)
    print(json.dumps(r, ensure_ascii=False, indent=2))