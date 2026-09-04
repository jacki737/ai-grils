# AI Grils（小暖）

<p align="center">一个跑在本机的 <b>AI 女友 / 桌宠</b>：二次元 Live2D 形象 + 多模型聊天 + 语音 + 记忆 + 人设 + 定时提醒 + 工具调用，可选微信桥接。</p>

> 本项目为学习作品。微信桥接依赖非官方 iLink 接口，仅供技术研究；生产/商用存在封号与合规风险。

## 效果预览

> 把你的录屏 GIF 和功能截图放到 `docs/` 目录后，取消下面注释即可显示（文件名已对应）。

<!--
![demo](docs/demo.gif)
![主界面](docs/screen-home.png)
![对话](docs/screen-chat.png)
-->

## 功能

- 二次元 Live2D 桌宠（Haru / shizuku 模型）
- 多角色人设 + 记忆
- 文字 / 语音对话（STT / TTS）
- 主动唤醒、定时任务、提醒
- 工具调用：打开应用、截图、网页搜索、文件、天气、代码/脚本执行等
- 微信机器人桥接（可选）

## 快速开始

### 1. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Windows-only 依赖：`pywin32`、`wmi`、`comtypes`、`pycaw`。首次使用 Playwright 请执行 `python -m playwright install chromium`。

### 2. 配置密钥

```bash
copy config.example.json config.json
```

然后编辑 `config.json`，填入对应 key；也可以在网页右上角设置里填（仅覆盖部分 key）。

### 3. 启动

```bash
run_server.bat
```

或 `python app.py`，浏览器打开 `http://127.0.0.1:9000`。桌面悬浮窗用 `start_pet.bat`。

## 配置项

| 字段 | 用途 / 供应商 |
| --- | --- |
| `mimo_key` | 主聊天模型 MiMo |
| `tool_key` | 工具调用 / 豆包兜底 |
| `vision_key` | 视觉模型（OpenRouter） |
| `zhipu_key` | 智谱 GLM 兜底 |
| `dashscope_key` / `dashscope_asr_key` | 阿里云百炼 TTS / ASR |
| `baidu_app_id` / `baidu_api_key` / `baidu_secret_key` | 百度语音合成 |
| `baidu_asr_app_id` / `baidu_asr_api_key` / `baidu_asr_secret_key` | 百度语音识别 |

## 打包

```bash
python build_exe.py
```

或以 `build.bat` 打包；生成安装包用 `AiGirlfriend.iss`（Inno Setup）。

## 微信桥接（可选）

```bash
copy weixin.env.example weixin.env
```

填入 iLink 的账号 token 等，再运行 `python wechat_bridge.py`。

## 安全与版权

- `config.json` 已在 `.gitignore`，切勿提交真实密钥。
- 本仓库已移除硬编码的百度 TTS 密钥；如该密钥历史上被推送到 GitHub，请立即到百度智能云轮换。
- Live2D 的 Haru / shizuku 为官方示例模型，商用或再分发前请确认授权，必要时替换为可商用模型。
