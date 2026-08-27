"""大脑: LLM 调用、Function Calling、多供应商降级、视觉分析"""
import json
import time
import urllib.request
from pathlib import Path

from core.persona import PERSONAS_DB


# ===== URL/模型名硬编码 =====
URL_CHAT = "https://api.xiaomimimo.com/v1"
MODEL_CHAT = "mimo-v2.5"
URL_TOOL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
MODEL_TOOL = "qwen3.7-plus"
URL_VISION = "https://openrouter.ai/api/v1"
MODEL_VISION = "google/gemma-4-31b-it:free"
URL_ZHIPU = "https://open.bigmodel.cn/api/paas/v4"
MODEL_ZHIPU = "glm-4.5-flash"


def load_config():
    p = Path(__file__).parent.parent.parent / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _has_image(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for part in c:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


def _zhipu_config():
    cfg = load_config()
    key = (cfg.get("zhipu_key") or "").strip()
    if not key:
        return None
    return {"base": URL_ZHIPU, "model": MODEL_ZHIPU, "key": key}


def _fallback_configs(tools=True):
    out = []
    if not tools:
        c = _zhipu_config()
        if c:
            out.append(c)
    return out


def call_llm(messages, tools=None):
    """统一 LLM 调用入口"""
    cfg = load_config()
    if tools:
        if _has_image(messages):
            base = URL_VISION
            model = MODEL_VISION
            key = (cfg.get("vision_key") or "").strip()
            if not key:
                return {"role": "assistant", "content": "（请先点右上角 ⚙ 设置, 填写 Vision token(OpenRouter), 否则我看不了屏幕哦）"}
        else:
            base = URL_TOOL
            model = MODEL_TOOL
            key = (cfg.get("tool_key") or "").strip()
            if not key:
                return {"role": "assistant", "content": "（请先点右上角 ⚙ 设置, 填写 Tool token(千问), 否则我没法执行操作哦）"}
    else:
        base = URL_CHAT
        model = MODEL_CHAT
        key = (cfg.get("mimo_key") or "").strip()
        if not key:
            return {"role": "assistant", "content": "（请先点右上角 ⚙ 设置, 填写 MiMo token, 否则我没法聊天哦）"}

    body = {"model": model, "messages": messages, "max_tokens": 1200, "temperature": 0.9}
    if tools and not _has_image(messages):
        body["tools"] = tools
    api_url = f"{base.rstrip('/')}/chat/completions"

    def _post():
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["choices"][0]["message"]

    last_err = None
    msg = None
    for attempt in range(3):
        try:
            msg = _post()
            break
        except urllib.error.HTTPError as e:
            last_err = e
            try:
                _eb = e.read().decode("utf-8", "ignore")[:500]
            except Exception:
                _eb = ""
            print(f"[LLM] HTTP {e.code} from {api_url}: {_eb}")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(8 + attempt * 12 if e.code == 429 else 2 + attempt * 3)
                continue
        except Exception as e:
            last_err = e
            print(f"[LLM-EXC] {type(e).__module__}.{type(e).__name__}: {e!r}")
            if attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
        break

    if msg is None:
        for fb in _fallback_configs(tools=bool(tools)):
            old_url = api_url
            base, model, key = fb["base"], fb["model"], fb["key"]
            body["model"] = model
            api_url = f"{base.rstrip('/')}/chat/completions"
            print(f"[{'工具' if tools else '聊天'}] 主模型失败({last_err}), 切兜底 -> {api_url} model={model}")
            try:
                msg = _post()
                break
            except urllib.error.HTTPError as e:
                last_err = e
                print(f"[兜底] 也失败: {e} body={e.read().decode('utf-8','ignore')[:800]}")
            except Exception as e:
                last_err = e
                print(f"[兜底] 也失败: {e}")
            finally:
                api_url = old_url

    if msg is None:
        if isinstance(last_err, urllib.error.HTTPError) and last_err.code == 429:
            return {"role": "assistant", "content": "（API 被限流啦，我喘口气，你半分钟后再叫我～）"}
        return {"role": "assistant", "content": f"（一时语塞：{last_err}）"}
    return msg