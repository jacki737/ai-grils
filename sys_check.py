#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统探测小程序 —— 根据真实环境(Windows 11 + WSL2)生成
运行: python sys_check.py
依赖: pip install psutil wmi (仅 Windows 需 wmi)
"""

import platform
import subprocess
import sys
from datetime import timedelta

try:
    import psutil
except ImportError:
    print("缺少 psutil，请: pip install psutil")
    sys.exit(1)

# Windows 专用
IS_WIN = platform.system() == "Windows"
if IS_WIN:
    try:
        import wmi
    except ImportError:
        wmi = None


def get_os_info():
    """操作系统版本"""
    return f"{platform.system()} {platform.release()} {platform.version()}"


def get_machine():
    """机型：Win32_ComputerSystem -> Win32_BIOS -> 注册表"""
    if IS_WIN and wmi:
        try:
            c = wmi.WMI()
            # 1) ComputerSystem
            for sys in c.Win32_ComputerSystem():
                manu = (sys.Manufacturer or "").strip()
                model = (sys.Model or "").strip()
                if manu or model:
                    return f"{manu} {model}".strip()
        except Exception:
            pass
        try:
            # 2) BIOS
            for bios in c.Win32_BIOS():
                manu = (bios.Manufacturer or "").strip()
                if manu:
                    return manu
        except Exception:
            pass
    # 3) 注册表
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\BIOS") as k:
                manu = winreg.QueryValueEx(k, "SystemManufacturer")[0]
                model = winreg.QueryValueEx(k, "SystemProductName")[0]
                return f"{manu} {model}".strip()
        except Exception:
            pass
    return platform.machine()


def get_cpu():
    """CPU 型号 + 当前占用"""
    name = platform.processor() or "未知"
    if IS_WIN and wmi:
        try:
            c = wmi.WMI()
            for proc in c.Win32_Processor():
                name = proc.Name.strip()
                break
        except Exception:
            pass
    usage = psutil.cpu_percent(interval=0.5)
    return f"{name} | 占用 {usage}%"


def get_memory():
    """内存"""
    vm = psutil.virtual_memory()
    return f"{vm.used / 1024**3:.1f}G 已用 / {vm.total / 1024**3:.1f}G 总量 ({vm.percent}%)"


def get_disks():
    """所有磁盘分区"""
    parts = []
    for p in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(p.mountpoint)
            parts.append(f"{p.device} {u.used//1024**3}G/{u.total//1024**3}G ({u.percent}%)")
        except PermissionError:
            parts.append(f"{p.device} 无权限")
    return " ; ".join(parts)


def get_uptime():
    """开机时长"""
    boot = psutil.boot_time()
    delta = timedelta(seconds=int(psutil.time.time() - boot))
    h = delta.days * 24 + delta.seconds // 3600
    return f"{h} 小时"


def get_battery():
    """电池"""
    if not hasattr(psutil, "sensors_battery"):
        return "非笔记本/不支持"
    bat = psutil.sensors_battery()
    if bat is None:
        return "无电池"
    return f"{bat.percent}% {'充电中' if bat.power_plugged else '放电中'}"


def get_wsl2():
    """WSL2 状态"""
    if not IS_WIN:
        return "非 Windows 环境"
    try:
        out = subprocess.check_output(["wsl.exe", "--status"], timeout=5)
        text = out.decode("utf-8", errors="ignore")
        # 只保留可打印字符(中文/英文/数字/常用标点)
        import re
        text = re.sub(r'[^\u4e00-\u9fff\w\s\-.:/()_=+\[\]{}@#%*]+', ' ', text)
        key = [l.strip() for l in text.splitlines() if "Default" in l or "Distribution" in l or "Kernel" in l]
        return " | ".join(key) if key else text[:200]
    except Exception as e:
        return f"探测失败: {e}"


def main():
    # Windows 控制台默认 GBK，改 UTF-8 防止中文乱码/报错
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("=== 系统探测报告 ===")
    print(f"系统版本: {get_os_info()}")
    print(f"机型: {get_machine()}")
    print(f"CPU: {get_cpu()}")
    print(f"内存: {get_memory()}")
    print(f"磁盘: {get_disks()}")
    print(f"开机时长: {get_uptime()}")
    print(f"电池: {get_battery()}")
    print(f"WSL2: {get_wsl2()}")


if __name__ == "__main__":
    main()