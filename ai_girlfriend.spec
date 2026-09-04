# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(SPECPATH)

# PyInstaller 配置
block_cipher = None

# 隐式导入
hiddenimports = [
    'uvicorn',
    'fastapi',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    'fastapi.openapi',
    'fastapi.staticfiles',
    'starlette.responses',
    'starlette.routing',
    'starlette.middleware',
    'starlette.middleware.cors',
    'pydantic',
    'pydantic_core',
    'playwright',
    'playwright.sync_api',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.JpegImagePlugin',
    'PIL.PngImagePlugin',
    'base64',
    'json',
    'sqlite3',
    'uuid',
    'threading',
    'asyncio',
    'urllib.request',
    'urllib.parse',
    'subprocess',
    'tempfile',
    'shutil',
    'pathlib',
    'datetime',
    'time',
    'hashlib',
    'hmac',
    'secrets',
    'logging',
    'email.mime.text',
    'email.mime.multipart',
    'email.mime.base',
    'email.encoders',
]

# 数据文件
datas = [
    (str(PROJECT_ROOT / 'static'), 'static'),
    (str(PROJECT_ROOT / 'config.json'), '.'),
    (str(PROJECT_ROOT / 'personas.json'), '.'),
    (str(PROJECT_ROOT / 'personas.db'), '.'),
    (str(PROJECT_ROOT / 'tools'), 'tools'),
    (str(PROJECT_ROOT / 'static' / 'css'), 'static/css'),
    (str(PROJECT_ROOT / 'static' / 'js'), 'static/js'),
    (str(PROJECT_ROOT / 'static' / 'live2d'), 'static/live2d'),
]

# 二进制文件
binaries = []

# 分析隐藏导入
def get_imports():
    return hiddenimports

a = Analysis(
    ['app.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
        'IPython',
        'jupyter',
        'notebook',
        'sphinx',
        'docutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AiGirlfriend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# 如果需要单文件模式，取消下面注释：
# exe = EXE(
#     pyz,
#     a.scripts,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     [],
#     name='AiGirlfriend',
#     debug=False,
#     bootloader_ignore_signals=False,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     runtime_tmpdir=None,
#     console=False,  # 无控制台窗口
#     disable_windowed_traceback=False,
#     argv_emulation=False,
#     target_arch=None,
#     codesign_identity=None,
#     entitlements_file=None,
#     icon='static/favicon.ico' if os.path.exists('static/favicon.ico') else None,
# )

# 创建安装包所需的额外文件
# Inno Setup 或 NSIS 可以使用这些文件创建安装程序