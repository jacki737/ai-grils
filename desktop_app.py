#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面 Live2D 宠物入口
打包后：双击 EXE → 只见桌面上一个可拖拽的 Live2D 角色
托盘图标 → 显示/隐藏 / 退出
"""
import os
import socket
import threading
import time
from pathlib import Path

import webview
import pystray
from PIL import Image


def _find_port(start=9000):
    for p in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


BASE_PORT = _find_port(9000)
BASE_URL = f"http://127.0.0.1:{BASE_PORT}"


def start_backend():
    import uvicorn
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=BASE_PORT, log_level="warning")


def _wait_backend(timeout=20):
    import urllib.request
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(BASE_URL + "/static/pet.html", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def create_window():
    window = webview.create_window(
        "AI Girlfriend",
        BASE_URL + "/static/pet.html",
        frameless=True,
        easy_drag=True,
        transparent=True,
        on_top=True,
        width=400,
        height=600,
        x=100, y=100,
    )
    return window


def setup_tray(window):
    state = {"hidden": False}

    def on_toggle(icon, item):
        try:
            if state["hidden"]:
                window.show()
            else:
                window.hide()
            state["hidden"] = not state["hidden"]
        except Exception:
            pass

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    icon_path = Path(__file__).parent / "static" / "favicon.ico"
    image = Image.open(icon_path)
    menu = pystray.Menu(
        pystray.MenuItem("显示/隐藏", on_toggle, default=True),
        pystray.MenuItem("退出", on_quit),
    )
    icon = pystray.Icon("AI_Girlfriend", image, "AI Girlfriend", menu)
    icon.run()


def main():
    # 1) 后台线程
    threading.Thread(target=start_backend, daemon=True).start()
    # 2) 等后端就绪
    _wait_backend()
    # 3) 创建窗口
    window = create_window()
    # 4) 托盘在单独线程
    threading.Thread(target=setup_tray, args=(window,), daemon=True).start()
    # 5) 启动 webview 主循环（阻塞），透明由 pywebview transparent=True 处理
    webview.start(debug=False)


if __name__ == "__main__":
    main()
