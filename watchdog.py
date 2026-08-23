#!/usr/bin/env python3
"""小暖服务守护 — 崩溃自动重启"""
import subprocess
import time
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 9000


def is_running():
    """检查 9000 端口是否在监听"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("127.0.0.1", PORT))
        s.close()
        return result == 0
    except Exception:
        return False


def start_server():
    """启动 uvicorn"""
    print(f"[{time.strftime('%H:%M:%S')}] 启动小暖服务 (端口 {PORT})...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=APP_DIR,
        stdout=open(os.path.join(APP_DIR, "server.log"), "a"),
        stderr=subprocess.STDOUT,
    )
    return proc


def main():
    print("🛡️ 小暖守护进程启动 (崩溃自动重启)")
    proc = None
    while True:
        if not is_running():
            print(f"[{time.strftime('%H:%M:%S')}] 服务未运行, 启动...")
            proc = start_server()
            # 等待就绪
            for _ in range(15):
                time.sleep(1)
                if is_running():
                    print(f"[{time.strftime('%H:%M:%S')}] ✅ 服务已就绪")
                    break
        time.sleep(5)


if __name__ == "__main__":
    main()
