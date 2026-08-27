# -*- coding: utf-8 -*-
# PyInstaller spec 文件
# 用法: pyinstaller build.spec
# 生成: dist/AI_Girlfriend.exe (单文件, 无控制台)

block_cipher = None

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('static', 'static'),
        ('tools', 'tools'),
        ('core', 'core'),
        ('config.json', '.'),
        ('personas.db', '.'),
        ('personas.json', '.'),
    ],
    hiddenimports=[
        # Web 框架
        'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.protocols',
        'fastapi', 'fastapi.routing', 'fastapi.middleware', 'fastapi.dependencies',
        'pydantic', 'pydantic.v1', 'pydantic_core',
        'starlette', 'starlette.routing', 'starlette.middleware',
        # 工具链
        'psutil', 'wmi', 'winreg',
        'webview', 'pystray', 'PIL', 'PIL._imaging', 'PIL.Image', 'PIL.ImageDraw',
        # 自有模块
        'tools.script_gen', 'tools.sysinfo', 'tools.weather', 'tools.sysinfo',
        'tools.reminders', 'tools.browser', 'tools.gui', 'tools.screen',
        'tools.search', 'tools.files', 'tools.code', 'tools.clipboard',
        'tools.notify', 'tools.schedule', 'tools.triggers', 'tools.shell',
        'tools.apps', 'tools._paths', 'tools.schema',
        # 核心
        'core.brain', 'core.memory', 'core.persona', 'core.tasks',
        'core.proactive',
        # 标准库/其他
        'json', 'sqlite3', 'datetime', 'pathlib', 'subprocess',
        'signal', 'platform', 're', 'urllib', 'urllib.parse', 'urllib.request',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy',
        'IPython', 'jupyter', 'pytest', 'unittest', 'test',
    ],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AI_Girlfriend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 关键：无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='static/favicon.ico',
)