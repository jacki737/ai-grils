"""项目根目录/静态资源路径(所有模块统一从这里取, 避免 __file__ 位置漂移)

背景: tools 从单个 tools.py 拆成了 tools/ 包后, 模块内的 __file__ 指向 .../tools/ 子目录,
不再等于项目根。若各模块各自用 dirname(__file__) 拼路径, 会全部指向错误位置。
因此这里集中定义三个基准路径, 其他模块一律 from ._paths import ... 使用:
  PROJECT_ROOT: 项目根目录(静态资源/日志/配置都放这里)
  STATIC_DIR:   PowerShell 助手脚本目录(open_app_helper/gui_helper/toast_helper/sysinfo_helper)
  CONFIG_PATH:  config.json(模型/密钥配置)
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")