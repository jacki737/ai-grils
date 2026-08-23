"""OpenAI 风格 tools 定义(给 DeepSeek function calling)"""
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "执行 shell/Linux 命令(只读或安全操作)。可用于查看文件、跑脚本、查询状态、操作 WSL 里的程序。危险命令(rm -rf/shutdown/格式化)会被拒绝。注意: 这是 WSL Linux 环境, Windows 命令(winget/powershell/cmd/reg/regedit/.exe)需用 powershell.exe 或 cmd.exe 前缀调用, 如: powershell.exe -Command 'winget install xxx'; Windows 文件路径要写成 /mnt/c/Users/xxx/...。重要: 打开/启动软件请用 open_app 工具, 禁止用 find/where/Get-ChildItem 全盘搜索 exe(会超时并被拒绝)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "要执行的 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时秒数, 默认 60"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文本文件内容(限制 200KB, 返回前 8000 字符)。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径, 如 /home/marka/xxx.py"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文本文件(新建或覆盖)。只能写 home 目录下的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "打开 Windows 软件。任意软件名(中文或英文)都行: 微信/WeChat、chrome、edge、notepad、calc、explorer、pycharm、code 或 exe 路径。会自动在注册表/开始菜单/常见目录找到安装位置并启动, 不依赖固定路径。打开软件首选本工具, 不要用 run_shell 去全盘找 exe。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "软件名: 微信/WeChat、chrome、edge、notepad、calc、explorer、pycharm、code 等, 或 exe 完整路径"},
                    "args": {"type": "string", "description": "可选参数, 如 chrome 的网址"},
                },
                "required": ["name"],
            },
        },
    },
{
        "type": "function",
        "function": {
            "name": "browser",
            "description": "控制 Chrome 网页(打开网址/执行JS/点击/输入/提取文字/截图/等待/后退/关闭)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["open", "eval", "click", "type", "text", "screenshot", "wait", "back", "close"], "description": "操作: open打开网页 / eval执行JS / click点击(selector) / type输入(text) / text提取页面文字 / screenshot截图 / wait显式等待(selector/state/timeout) / back后退 / close关闭"},
                    "url": {"type": "string", "description": "open 时的网址"},
                    "js": {"type": "string", "description": "eval 时执行的 JS 表达式"},
                    "selector": {"type": "string", "description": "click/type/wait 时的 CSS 选择器"},
                    "text": {"type": "string", "description": "type 时输入的文字"},
                    "state": {"type": "string", "enum": ["attached", "detached", "visible", "hidden"], "description": "wait 时等待的元素状态"},
                    "timeout": {"type": "integer", "description": "wait 时的超时毫秒数"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_code",
            "description": "委托 Claude Code CLI 写代码/改代码(DeepSeek 后端, 会自动落盘)。适合实现功能、重构、修 bug。",
            "parameters": {
                "type": "object",
                "properties": {
                    "req": {"type": "string", "description": "开发需求描述(要做什么、改哪个文件、注意什么)"},
                    "cwd": {"type": "string", "description": "工作目录, 默认 /home/marka"},
                    "timeout": {"type": "integer", "description": "超时秒数, 默认 600"},
                },
                "required": ["req"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot",
            "description": "截取 Windows 桌面屏幕, 返回 image_base64(JPEG 图片数据)。适合查看当前屏幕上有什么、或把屏幕保存成图片文件。用户说'保存到E盘/D盘'时, 用 save_to 传 Windows 绝对路径(如 E:\\\\截图_20260822.png 或 E:\\\\screens\\\\shot.png)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "save_to": {"type": "string", "description": "可选: 把原图另存到该 Windows 路径, 如 E:\\\\截图.png; 用户没说保存就不传"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard",
            "description": "读写 Windows 剪贴板: get 读取当前剪贴板内容; set 写入指定内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["get", "set"], "description": "get=读取 / set=写入"},
                    "text": {"type": "string", "description": "set 时写入的文本内容"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify",
            "description": "发送 Windows 桌面托盘通知(右下角弹气泡)。适合提醒用户重要事情、任务完成、定时提醒。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "通知正文"},
                    "title": {"type": "string", "description": "通知标题, 默认'小暖'"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "按文件名或内容搜索文件。默认在 /home/marka 和 C 盘用户目录下搜索。content=True 时按文件内容搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索关键词/文件名片段"},
                    "path": {"type": "string", "description": "可选, 指定搜索目录, 默认 home 和 C 盘用户目录"},
                    "content": {"type": "boolean", "description": "True=按文件内容搜索, False=按文件名搜索"},
                    "max_results": {"type": "integer", "description": "最多返回条数, 默认 30"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "查看系统状态: Windows 主机(系统版本/CPU型号/CPU占用/内存/各磁盘占用/电池/开机时长) + WSL 环境(负载/内存/温度)。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_scheduled",
            "description": "定时任务: add 一次性延迟(delay 秒后执行)或 crontab 周期任务(cron 表达式, 如 '0 9 * * *' 每天9点); list 查看已有任务; remove 删除任务。输出写入 scheduled.log。定时提醒用户时, cmd 务必写成 notify text='提醒内容' title='标题' 这种格式(例如: notify text='该喝水了' title='小暖'), 系统会自动转成桌面通知; 不要手写 powershell 命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "要执行的 shell 命令(add 时必填)。提醒用户用: notify text='内容' title='标题'"},
                    "action": {"type": "string", "enum": ["add", "list", "remove"], "description": "add=新建 / list=列出 / remove=删除, 默认 add"},
                    "cron": {"type": "string", "description": "cron 表达式(周期任务), 留空则用 delay 一次性执行"},
                    "delay": {"type": "integer", "description": "一次性任务: 多少秒后执行, 默认 0"},
                    "name": {"type": "string", "description": "任务名(便于 list/remove 识别)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gui_do",
            "description": "屏幕GUI操作闭环: 在屏幕上完成一个软件界面内的任务(如'在记事本里输入文字'、'把网易云播放列表点开'、'选中并复制某段文字')。会自动截屏→用视觉模型看屏幕→决定并执行鼠标/键盘动作→重新截屏复核效果→直到完成。target_hint 传目标窗口标题词(如'记事本'/'网易云音乐'), 任务会自动把窗口置前防遮挡。软件没打开时先调 open_app 打开, 再用本工具操作界面。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "要在屏幕上完成的任务描述, 如'在记事本里输入 你好世界'"},
                    "target_hint": {"type": "string", "description": "目标窗口标题关键词(如'记事本'/'网易云音乐'), 用于置前目标窗口并枚举其控件"},
                    "max_steps": {"type": "integer", "description": "最大步数上限, 默认 8, 防死循环"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_action",
            "description": "直接控制 Windows 鼠标/键盘(单个动作, 不做闭环复核)。action: move 移动鼠标到坐标 / left_click 左键单击 / double_click 双击 / right_click 右键 / scroll 滚动(text=up或down) / type 输入文字(支持中文) / key 按键(如 enter、ctrl+s)。坐标是屏幕物理像素。需要操作软件界面内的具体按钮时, 先调 get_controls 拿到控件坐标, 或直接用 gui_do 走完整闭环。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["move", "left_click", "double_click", "right_click", "scroll", "type", "key"], "description": "要执行的动作"},
                    "x": {"type": "integer", "description": "X 坐标(物理像素)"},
                    "y": {"type": "integer", "description": "Y 坐标(物理像素)"},
                    "text": {"type": "string", "description": "type 时输入的文字 / scroll 方向(up/down) / key 的按键(如 enter、ctrl+s)"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_controls",
            "description": "枚举 Windows 前台(或指定标题窗口)的可交互控件树(无障碍 UIA), 返回每个控件的名称/类型/屏幕物理坐标中心。用于操作软件界面前了解有哪些可点的按钮/输入框/菜单项。",
            "parameters": {
                "type": "object",
                "properties": {
                    "window": {"type": "string", "description": "窗口标题关键词(可选), 留空用当前前台窗口"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "播放音乐: 先发系统媒体键尝试恢复播放; 若没有播放会话则打开网易云音乐并自动点一首歌。用户说'放首歌/来点音乐/播放音乐'时用这个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "音乐应用名, 默认'网易云音乐'"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": "系统媒体控制: 播放/暂停、切歌、音量。用户说'暂停/继续播放/下一首/上一首/音量大点/小点/静音'时用这个。基于 Windows 全局媒体键, 网易云音乐在后台也能控制。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["play_pause", "next", "previous", "volume_up", "volume_down", "mute"], "description": "play_pause=播放/暂停切换, next=下一首, previous=上一首, volume_up/down=音量, mute=静音"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_specific_song",
            "description": "搜索并播放指定歌手/歌名。用户说'放周杰伦的晴天'/'播放稻香'/'点首歌 xxx'时用这个。参数 query 传完整关键词如 '周杰伦 晴天' 或 '稻香'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如 '周杰伦 晴天' 或 '稻香'"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "设置一次性定时提醒(到点会主动语音播报)。用户说'提醒我十分钟后喝水'/'提醒我明天早上九点开会'/'一分钟后叫醒我'时用这个。参数 raw 传「提醒我」后面的原文, 如 '十分钟后喝水'、'明天早上九点开会'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string", "description": "时间+事项原文, 如 '十分钟后喝水' 或 '明天早上九点开会'"}
                },
                "required": ["raw"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "列出所有待提醒事项。用户问'我有什么提醒'/'提醒列表'时用这个。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_trigger",
            "description": "设置条件触发/周期任务: 条件成立或每隔一段时间就自动行动。用户说'如果明天下雨就提醒我带伞'/'每当有重大AI新闻就告诉我'/'每隔30分钟提醒我喝水'时用这个。参数 raw 传完整原句。",
            "parameters": {
                "type": "object",
                "properties": {
                    "raw": {"type": "string", "description": "完整触发任务原句, 如 '如果明天下雨就提醒我带伞' 或 '每隔30分钟提醒我喝水'"}
                },
                "required": ["raw"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_triggers",
            "description": "列出所有在册的条件触发/周期任务。用户问'我有哪些触发任务'/'周期任务列表'时用这个。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_search",
            "description": "在指定桌面应用里搜索关键词(如今日头条/微信等): 自动定位该应用搜索框输入并回车。用户说'在XX里搜YY'/'打开XX查询YY'时, 先 open_app 打开应用再用本工具。找不到窗口或搜索框会诚实报错。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string", "description": "应用名, 如 '今日头条'/'微信'"},
                    "kw": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["app", "kw"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查城市天气(当前+今明预报)。用户说'查天气/今天天气怎么样/北京天气'时用这个, 比浏览器爬虫快且稳。参数 city 传中文城市名如 '北京'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名, 如 '北京'/'杭州', 默认北京"}
                },
            },
        },
    },
]