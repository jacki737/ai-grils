"""定时任务: 一次性延迟执行 + crontab 周期任务

两种任务都落到系统层(后台进程 / crontab), 与服务器进程无关, 服务器重启也不丢:
  一次性: nohup bash -c "sleep N; 命令" 后台跑, 输出写 scheduled.log;
  周期:   把命令写进 scheduled_jobs/xxx.sh, 再注册 crontab 调用。
模型可能把"notify text=..."工具式写法直接塞进 cmd, _sched_real_cmd 会自动翻译成
真实 python 调用(from tools import notify), 否则会报 command not found。
"""
import json
import os
import re
import shlex
import subprocess

from ._paths import PROJECT_ROOT
from .safety import _check_shell_safety

_SCHED_DIR = os.path.join(PROJECT_ROOT, "scheduled_jobs")
_SCHED_LOG = os.path.join(PROJECT_ROOT, "scheduled.log")


def _sched_real_cmd(cmd: str) -> str:
    """把模型可能给的"工具式指令"翻译成真正的 shell 命令

    run_scheduled 的 cmd 是 shell 命令; 但模型常直接写 notify text='...' title='...'
    这种工具调用语法, 直接跑会报 command not found。这里自动翻译成 python 调用。
    """
    m = re.match(r"^\s*notify(?:\.exe)?\s+(.+)$", cmd, re.S)
    if m:
        try:
            parts = shlex.split(m.group(1))
        except Exception:
            parts = m.group(1).split()
        kv = {}
        for p in parts:
            if "=" in p:
                k, _, v = p.partition("=")
                kv[k.lower()] = v.strip("'\"")
        text = kv.get("text") or kv.get("msg") or ""
        title = kv.get("title") or "小暖"
        if not text:
            text = cmd.replace("notify", "", 1).strip()
        py = f"from tools import notify; print(notify({json.dumps(text[:300])}, {json.dumps(title[:50])}))"
        return "cd " + shlex.quote(PROJECT_ROOT) + " && python3 -c " + shlex.quote(py)
    return cmd


def run_scheduled(cmd: str = "", action: str = "add", cron: str = "", delay: int = 0, name: str = ""):
    """定时任务管理:
      run_scheduled('echo hi', delay=60)          60秒后执行一次(后台, 不阻塞)
      run_scheduled('bash /x.sh', cron='0 9 * * *')  每天9点执行(crontab, 持久化)
      run_scheduled('', action='list')             列出已建定时任务
      run_scheduled('', action='remove', name='xx') 删除指定定时任务
      cmd 也支持 notify text='...' title='...' 写法, 自动翻译成桌面通知。
    延迟任务输出写入 scheduled.log; cron 任务输出同样写入。
    """
    cmd = (cmd or "").strip()
    action = (action or "add").lower()
    try:
        if action == "list":
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
            lines = [l for l in (p.stdout or "").splitlines() if "#sched-" in l or l.strip() and not l.startswith("#")]
            sched = []
            for l in lines:
                m = re.search(r"#sched-(\S+)#(.*)", l)
                if m:
                    sched.append({"id": m.group(1), "name": m.group(2) or m.group(1), "cron_line": l[:120]})
            return {"ok": True, "count": len(sched), "tasks": sched or ["(暂无定时任务)"]}

        if action == "remove":
            name = (name or "").strip()
            p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
            lines = [l for l in (p.stdout or "").splitlines()]
            kept = [l for l in lines if not (name and name in l)]
            if len(kept) == len(lines):
                return {"ok": False, "error": f"未找到含 {name} 的定时任务"}
            subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True, timeout=15)
            return {"ok": True, "msg": f"已删除定时任务: {name}"}

        if action != "add":
            return {"ok": False, "error": f"未知动作: {action}(仅 add/list/remove)"}
        if not cmd:
            return {"ok": False, "error": "命令为空"}
        # 翻译工具式指令(notify ...)成真实 shell 命令后再做安全检查
        cmd = _sched_real_cmd(cmd)
        danger = _check_shell_safety(cmd)
        if danger:
            return {"ok": False, "error": danger}

        # 一次性延迟任务: 后台 nohup sleep 后执行, 独立于服务器进程, 服务器重启也不丢
        if cron == "" or cron is None:
            delay = int(delay or 0)
            if delay < 0:
                delay = 0
            os.makedirs(os.path.dirname(_SCHED_LOG), exist_ok=True)
            subprocess.Popen(
                ["bash", "-lc", f"sleep {delay}; {cmd} >> {_SCHED_LOG} 2>&1"],
                start_new_session=True,
            )
            return {"ok": True, "msg": f"已安排 {delay} 秒后执行一次(结果写入 scheduled.log)"}

        # cron 周期任务: 写脚本文件 + 注册 crontab, 持久化
        os.makedirs(_SCHED_DIR, exist_ok=True)
        task_id = "sched-" + __import__("uuid").uuid4().hex[:8]
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]", "_", name or task_id)
        script = os.path.join(_SCHED_DIR, safe_name + ".sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\n" + cmd + "\n")
        os.chmod(script, 0o755)
        cron_line = f"{cron} /bin/bash {script} >> {_SCHED_LOG} 2>&1  #sched-{task_id}#{safe_name}"
        p = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=15)
        current = (p.stdout or "").rstrip("\n")
        new = current + "\n" + cron_line if current else cron_line
        subprocess.run(["crontab", "-"], input=new + "\n", text=True, timeout=15)
        return {"ok": True, "msg": f"已创建定时任务: {safe_name} ({cron}), 输出写入 scheduled.log", "id": task_id}
    except Exception as e:
        return {"ok": False, "error": f"定时任务操作失败: {e}"}