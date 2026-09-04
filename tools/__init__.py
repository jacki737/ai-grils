"""tools 包入口: 组装工具注册表, 保持与旧 tools.py 完全一致的对外接口
(TOOL_FUNCS / TOOLS_SCHEMA / exec_tool / APP_ALIASES / BUILTIN_CMDS / 各工具函数)

这是整个 tools 包的门面: app.py 只 from tools import ... 这一个入口,
不直接依赖内部模块。职责:
  1) 把所有工具函数收集进 TOOL_FUNCS 注册表(name -> 函数);
  2) 定义 exec_tool(name, args): 按名字调用工具 + 统一记日志;
  3) 对外再导出 TOOLS_SCHEMA(function calling 定义)和 APP_ALIASES/BUILTIN_CMDS。
"""
import json
import os

from ._paths import PROJECT_ROOT
from .apps import APP_ALIASES, BUILTIN_CMDS, open_app
from .browser import browser
from .clipboard import clipboard
from .code import write_code
from .files import read_file, write_file
from .gui import get_controls, gui_do, media_control, mouse_action, play_music, play_specific_song, app_search
from .notify import notify
from .reminders import add as add_reminder, list_pending as list_reminders
from .schedule import run_scheduled
from .triggers import add_trigger, list_triggers
from .schema import TOOLS_SCHEMA
from .screen import screenshot
from .search import search_files
from .shell import run_shell
from .sysinfo import system_info
from .weather import get_weather
from .script_gen import gen_script
from .train_ticket import query_trains
from .price_search import search_price

# 工具注册表: 名字 -> 函数。exec_tool 靠它派发, 加新工具要在这里登记。
TOOL_FUNCS = {
    "run_shell": run_shell,
    "read_file": read_file,
    "write_file": write_file,
    "open_app": open_app,
    "browser": browser,
    "write_code": write_code,
    "screenshot": screenshot,
    "clipboard": clipboard,
    "notify": notify,
    "search_files": search_files,
    "system_info": system_info,
    "run_scheduled": run_scheduled,
    "gui_do": gui_do,
    "mouse_action": mouse_action,
    "get_controls": get_controls,
    "play_music": play_music,
    "play_specific_song": play_specific_song,
    "app_search": app_search,
    "media_control": media_control,
    "set_reminder": add_reminder,
    "list_reminders": list_reminders,
    "add_trigger": add_trigger,
    "list_triggers": list_triggers,
    "get_weather": get_weather,
    "gen_script": gen_script,
    "query_trains": query_trains,
    "search_price": search_price,
}

# 日志落在项目根(拆分后 __file__ 指向 tools/ 子目录, 不能再用它拼路径)
_TOOLS_LOG = os.path.join(PROJECT_ROOT, "tools.log")
_BUG_REPORT_LOG = os.path.join(PROJECT_ROOT, "bug_reports.log")


def _log_tool_call(name: str, args: dict, result: dict):
    """记录工具调用日志: 每次写 tools.log, 失败(ok=false)额外写 bug_reports.log

    日志写失败只 print 提醒, 绝不影响工具执行本身。
    """
    try:
        import datetime
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 参数/结果都截断到前 200 字符, 防止日志文件无限膨胀
        arg_str = json.dumps(args, ensure_ascii=False)[:200]
        res_str = json.dumps(result, ensure_ascii=False)[:200]
        with open(_TOOLS_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] 调用: {name} 参数: {arg_str} 结果: {res_str}\n")
        # result 可能是普通字符串(如 gui_do 返回的是口语化文本), 不是 dict 时跳过 ok 判断
        if isinstance(result, dict) and not result.get("ok"):
            # 失败时额外记录 bug_reports.log, 方便事后排查
            err = result.get("error") or result.get("output") or "未知错误"
            with open(_BUG_REPORT_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] 工具失败: {name} 错误: {err}\n")
    except Exception as e:
        print(f"[工具日志] 写入失败: {e}")


def exec_tool(name: str, args: dict):
    """按名字执行工具, 返回统一 dict

    流程: 查注册表 → 找到就 fn(**args) 调用 → 统一记日志。
    参数错误(TypeError)和运行时异常都会被兜住, 转成 {"ok": False, "error": ...},
    保证模型侧永远拿到稳定结构、服务器永不因单次工具调用崩掉。
    """
    fn = TOOL_FUNCS.get(name)
    if not fn:
        result = {"ok": False, "error": f"未知工具: {name}"}
        _log_tool_call(name, args, result)
        return result
    try:
        if not isinstance(args, dict):
            args = {}
        result = fn(**args)
        _log_tool_call(name, args, result)
        return result
    except TypeError as e:
        result = {"ok": False, "error": f"参数错误: {e}"}
        _log_tool_call(name, args, result)
        return result
    except Exception as e:
        result = {"ok": False, "error": f"工具异常: {e}"}
        _log_tool_call(name, args, result)
        return result