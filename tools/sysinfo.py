"""系统状态: Windows 主机 + WSL 环境

调 static/sysinfo_helper.ps1 一次性拿 Windows 主机信息(系统/CPU/内存/磁盘/电池/开机时长),
再在本机(WSL)读 /proc 拿负载/内存/温度。返回的 dict 全部是给模型看的中文描述文本。
"""
import json
import os
import subprocess

from ._paths import STATIC_DIR


def _win_sysinfo():
    """通过 PowerShell 读取 Windows 主机状态, 返回 dict(失败返回空)

    sysinfo_helper.ps1 把结果序列化成 JSON 打印, 这里解析成 dict。
    找不到脚本或调用失败都返回 {}, 由上层显示"未知", 不影响整体。
    """
    script = os.path.join(STATIC_DIR, "sysinfo_helper.ps1")
    if not os.path.exists(script):
        return {}
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
            capture_output=True, timeout=30,
        )
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        return json.loads(out) if out else {}
    except Exception:
        return {}


def _wsl_sysinfo():
    """探测 WSL/Linux 子系统状态(短超时, 不可用时优雅返回提示文本, 绝不抛错)"""
    out = {}

    def sh(c, timeout=5):
        try:
            p = subprocess.run(["wsl.exe", "-e", "bash", "-lc", c],
                               capture_output=True, text=True, timeout=timeout)
            return (p.stdout or "").strip()
        except Exception:
            return ""

    # 先快速探测 WSL 是否可用(1秒探活)
    probe = ""
    try:
        p = subprocess.run(["wsl.exe", "echo", "ok"], capture_output=True, text=True, timeout=3)
        probe = (p.stdout or "").strip()
    except Exception:
        probe = ""

    if probe != "ok":
        return {"Linux/WSL": "未检测到 WSL 子系统"}

    load = sh("cat /proc/loadavg 2>/dev/null | cut -d' ' -f1-3")
    kernel = sh("uname -r")
    mem = sh("free -h | awk '/Mem:/{print $3\" 已用 / \"$2\" 总量\"}'")
    temp = sh("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null | awk '{print int($1/1000)\"°C\"}'")

    out["Linux内核"] = kernel or "未知"
    out["Linux负载(1/5/15分钟)"] = load or "未知"
    out["Linux内存"] = mem or "未知"
    if temp:
        out["Linux温度"] = temp
    return out


_PART_KEYS = {
    "cpu": ["CPU占用", "CPU"],
    "内存": ["内存"],
    "磁盘": ["磁盘"],
    "电池": ["电池"],
    "开机": ["开机时长"],
}


def system_info(part: str = ""):
    """查看系统状态: Windows 主机(系统/CPU/内存/磁盘/电池/开机时长) + Linux/WSL(如有)

    part: 只看某一部分(cpu/内存/磁盘/电池/开机), 空则全量。
    返回的每个键都是给模型看的中文描述; 细分查询时附带 msg 口语播报。
    """
    try:
        w = _win_sysinfo()
        result = {
            "ok": True,
            "系统": ((w.get("os") or "未知") + " " + (w.get("os_build") or "")).strip(),
            "机型": w.get("machine") or "未知",
            "CPU": (w.get("cpu") or "未知")[:70],
            "CPU占用": w.get("cpu_load") or "未知",
            "内存": (str(w.get("mem_used_g")) + " G 已用 / " + str(w.get("mem_total_g")) + " G 总量") if w.get("mem_total_g") else "未知",
            "磁盘": w.get("disk") or "未知",
            "开机时长": (str(w.get("uptime_h")) + " 小时") if w.get("uptime_h") is not None else "未知",
            "电池": w.get("battery") or "非笔记本/未知",
        }
        # Linux/WSL 部分: 探测失败只加一行提示, 不影响整体
        try:
            result.update(_wsl_sysinfo())
        except Exception:
            result["Linux/WSL"] = "探测失败"
        part = (part or "").strip().lower()
        if part and part in _PART_KEYS:
            keys = _PART_KEYS[part]
            picked = [(k, result.get(k, "未知")) for k in keys]
            result = {"ok": True, "msg": "，".join(f"{k}{v}" for k, v in picked),
                      **{k: v for k, v in picked}}
        return result
    except Exception as e:
        return {"ok": False, "error": f"获取系统状态失败: {e}"}