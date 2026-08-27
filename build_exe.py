#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键打包脚本：生成桌面 Live2D 宠物 EXE
运行: python build_exe.py
产物: dist/AI_Girlfriend.exe
"""
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
SPEC = ROOT / "build.spec"

REQUIREMENTS = [
    "pywebview",
    "pystray",
    "pillow",
    "pyinstaller",
    "pywin32",  # Windows 托盘需要
]

def run(cmd, cwd=None):
    print(f"\n>>> {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}")

def main():
    print("=== 开始打包桌面 Live2D 宠物 ===")

    # 1. 确保依赖
    print("\n[1/4] 安装依赖...")
    run([sys.executable, "-m", "pip", "install", "-U", "pip"])
    run([sys.executable, "-m", "pip", "install"] + REQUIREMENTS)

    # 2. 确保 favicon.ico 存在
    favicon = ROOT / "static" / "favicon.ico"
    if not favicon.exists():
        print("\n[2/4] 生成默认图标...")
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 56, 56], fill="#ff6b9d")
        favicon.parent.mkdir(exist_ok=True)
        img.save(favicon, format="ICO")
        print(f"  已生成: {favicon}")

    # 3. 运行 PyInstaller (在项目根目录下运行，确保输出到项目 dist/)
    print("\n[3/4] 运行 PyInstaller (可能需要 1-3 分钟)...")
    if SPEC.exists():
        run([sys.executable, "-m", "PyInstaller", "--clean", str(SPEC)], cwd=str(ROOT))
    else:
        raise FileNotFoundError(f"找不到 {SPEC}")

    # 4. 验证产物 (PyInstaller 输出到项目根目录下的 dist/)
    exe = ROOT / "dist" / "AI_Girlfriend.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"\n=== 打包成功 ===")
        print(f"产物: {exe}")
        print(f"大小: {size_mb:.1f} MB")
        print(f"\n双击运行: {exe}")
        print("桌面将出现一个可拖拽的 Live2D 角色，右下角托盘可退出。")
    else:
        raise FileNotFoundError("EXE 未生成，请检查上面报错")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] 打包失败: {e}")
        sys.exit(1)