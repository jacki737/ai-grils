#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面 Live2D 宠物入口
打包后：双击 EXE → 只见桌面上一个可拖拽的 Live2D 角色
右键托盘图标 → 设置 / 退出
"""
import sys
import os
import threading
import time
from pathlib import Path

import webview
import pystray
from PIL import Image

# ────────────────────────────────────────
# 1. 启动 FastAPI 后台 (复用现有 app.py)
# ────────────────────────────────────────
def start_backend():
    import uvicorn
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="warning")

# ────────────────────────────────────────
# 2. 创建无边框透明窗口加载 Live2D
# ────────────────────────────────────────
def create_window():
    # 必须走本地服务器加载, 否则页面里的 /static 绝对路径失效
    window = webview.create_window(
        "AI Girlfriend",
        "http://127.0.0.1:9000/static/pet.html",
        frameless=True,
        easy_drag=True,     # 按住页面即可拖动窗口
        transparent=True,
        on_top=True,
        width=400,
        height=600,
        x=100, y=100,
    )
    return window


def _apply_colorkey():
    """Win32 色键抠像: 把窗口里所有 #00ff00 像素抠成全透明(桌面宠物经典方案)。

    必须等窗口句柄就绪后调用(通过 webview.start(func) 在 GUI 循环启动后执行)。
    """
    import ctypes
    hwnd = None
    for _ in range(100):
        try:
            w = webview.windows[0]
            if getattr(w, "native", None) is not None:
                hwnd = int(w.native.Handle)
                break
        except Exception:
            pass
        time.sleep(0.2)
    if not hwnd:
        print("[colorkey] 未拿到窗口句柄, 透明失败")
        return
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    LWA_COLORKEY = 0x00000001
    COLORREF_GREEN = 0x0000FF00  # COLORREF 是 0x00BBGGRR, 绿色=0x0000FF00
    user32 = ctypes.windll.user32
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)
    user32.SetLayeredWindowAttributes(hwnd, COLORREF_GREEN, 0, LWA_COLORKEY)
    print("[colorkey] 透明已应用 hwnd=", hwnd)

# ────────────────────────────────────────
# 3. 系统托盘
# ────────────────────────────────────────
window = create_window()

    # 3) 系统托盘
    setup_tray(window)

    # 4) 关键修复：去除窗口系统阴影，配合 pet.html 透明背景
    try:
        window.set_opacity(1.0)
    except Exception:
        pass

# ────────────────────────────────────────
# 4. 主流程
# ────────────────────────────────────────
def _wait_backend(timeout=20):
    """轮询直到本地后端就绪"""
    import urllib.request
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen("http://127.0.0.1:9000/static/pet.html", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    # 1) 后台线程
    threading.Thread(target=start_backend, daemon=True).start()
    # 2) 等后端就绪
    _wait_backend()

    # 2) 创建窗口
    window = create_window()

    # 3) 托盘在单独线程
    threading.Thread(target=setup_tray, args=(window,), daemon=True).start()

    # 4) 启动 webview 主循环（阻塞）
    webview.start(debug=False)

if __name__ == "__main__":
    main()