"""视觉模型(VLM)调用: 主模型失败自动降级 glm-4v-flash

负责把"截图 + 问题"发给视觉大模型并拿回文本回复。
主视觉走 OpenRouter(nemotron-nano-12b-v2-vl:free, key 从 config.json 的 vision_key 读),
报错/超时时自动换免费的 glm-4v-flash(智谱)兜底重试。
这是 gui.py 的"眼睛"——屏幕闭环每次截屏后都通过这里让模型"看"。

历史踩坑(为什么不用别的实现):
  - 用 PowerShell Invoke-RestMethod 转发请求: 响应解析在部分模型上返回 null, 不稳定;
  - urllib 直连(本文件): 与 OpenAI 兼容接口直接对话, 已实测能读出图片里的文字。故统一走 urllib。
"""
import json
import urllib.request

from ._paths import CONFIG_PATH

# 降级视觉模型(免费, 验证可用): 主模型网络错误/超时/不可用时兜底
_VLM_FALLBACK_MODEL = "glm-4v-flash"
_VLM_FALLBACK_BASE = "https://open.bigmodel.cn/api/paas/v4"
_VLM_FALLBACK_KEY = ""


def _vision_config():
    """视觉模型配置: URL/模型已硬编码(OpenRouter 免费模型), key 从 config.json 读取"""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    base = "https://openrouter.ai/api/v1"
    key = (cfg.get("vision_key") or "").strip()
    model = "google/gemma-4-31b-it:free"
    return base, key, model, {}


def _ask_vlm_once(image_b64, user_text, system, base, key, model, extra, timeout=90):
    """单次视觉模型调用: 发送截图+文本, OpenAI 兼容格式, 返回文本回复。失败抛异常。

    请求体: 系统提示词 + 一条 user 消息(文本 + 图片 data URL)。
    图片用 "data:image/jpeg;base64," + base64 前缀内联发送, 不依赖图床。
    """
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or "你是一个屏幕内容描述助手。"},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
            ]},
        ],
        "temperature": 0.1,
    }
    if extra:
        payload.update(extra)
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]


# OpenRouter 免费视觉模型池: 主模型限流(429)/下线(404)时自动轮换下一个
_VLM_FREE_POOL = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "thinkingmachines/inkling-small:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
]

# 失败模型冷却表: {模型名: 失败时间戳}——10 分钟内不再试, 避免每步都挨个撞死模型
_VLM_COOLDOWN = {}
_VLM_COOLDOWN_SEC = 600


def _ask_vlm(image_b64, user_text, system=None):
    """配置驱动的视觉模型调用: 免费池逐个轮换(429/404自动换), 最后降级 glm-4v-flash。

    通常不直接抛异常——全部失败才往上抛, 由调用方(gui.py)按"视觉暂时不可用"处理。
    """
    import time as _time
    base, key, model, extra = _vision_config()
    candidates = [model] + [m for m in _VLM_FREE_POOL if m != model]
    now = _time.time()
    alive = [m for m in candidates if now - _VLM_COOLDOWN.get(m, 0) > _VLM_COOLDOWN_SEC]
    if not alive:
        alive = candidates  # 全在冷却也硬着头皮试一轮主模型, 免得永远卡死
    last_exc = None
    for m in alive:
        try:
            return _ask_vlm_once(image_b64, user_text, system, base, key, m, extra)
        except Exception as exc:
            last_exc = exc
            _VLM_COOLDOWN[m] = _time.time()
            print(f"[gui] 视觉模型 {m} 失败({exc}), 换下一个 (冷却10分钟)")
            continue
    # 免费池全挂 -> 智谱兜底(需 zhipu_key)
    fb_key = _VLM_FALLBACK_KEY
    if not fb_key:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                fb_key = json.load(f).get("zhipu_key") or ""
        except Exception:
            fb_key = ""
    if not fb_key:
        raise last_exc or RuntimeError("所有视觉模型均不可用")
    print(f"[gui] 免费池全挂, 降级 {_VLM_FALLBACK_MODEL}")
    return _ask_vlm_once(image_b64, user_text, system,
                         _VLM_FALLBACK_BASE, fb_key, _VLM_FALLBACK_MODEL, {}, timeout=60)