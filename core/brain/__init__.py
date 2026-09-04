"""大脑: LLM 调用、Function Calling、多供应商降级、视觉分析"""
import json
import time
import urllib.request
from pathlib import Path

from core.persona import PERSONAS_DB


# ===== URL/模型名硬编码 =====
# 主聊天: 小米 MiMo(实测闲聊响应最快, 余额计费)
URL_CHAT = "https://api.xiaomimimo.com/v1"
MODEL_CHAT = "mimo-v2.5"
# 聊天兜底1: 火山 Coding Plan 豆包(包月, 必须关思考 17s→2.5s; 同端点 glm-5-3-flash 强制思考 8~17s 不用于闲聊)
URL_DOUBAO = "https://ark.cn-beijing.volces.com/api/coding/v3"
MODEL_DOUBAO = "doubao-seed-code"
URL_TOOL = "https://ark.cn-beijing.volces.com/api/coding/v3"
MODEL_TOOL = "doubao-seed-code"
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


def _doubao_config():
    cfg = load_config()
    key = (cfg.get("tool_key") or "").strip()
    if not key:
        return None
    return {"base": URL_DOUBAO, "model": MODEL_DOUBAO, "key": key}


def _fallback_configs(tools=True):
    out = []
    if not tools:
        # 聊天兜底链: 火山豆包(包月) -> 智谱 GLM-4.5-flash(免费), 都注入反客服腔提示
        for c in (_doubao_config(), _zhipu_config()):
            if c:
                c = dict(c)
                c["extra_system"] = "严禁使用\"收到\"\"马上处理\"\"好的稍等\"\"马上安排\"\"正在为您\"\"正在处理\"等客服/助理腔，直接自然回复。"
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
                return {"role": "assistant", "content": "（请先点右上角 ⚙ 设置, 填写 Tool token(火山 Coding Plan), 否则我没法执行操作哦）"}
    else:
        base = URL_CHAT
        model = MODEL_CHAT
        key = (cfg.get("mimo_key") or "").strip()
        if not key:
            return {"role": "assistant", "content": "（请先点右上角 ⚙ 设置, 填写 MiMo token, 否则我没法聊天哦）"}

    # 闲聊限制输出长度: 长回复非流式生成要 20~30s, 是语音回复慢的主因; 工具/视觉保留 3000
    body = {"model": model, "messages": messages, "max_tokens": 3000 if tools else 1000, "temperature": 0.9}
    if tools and not _has_image(messages):
        body["tools"] = tools
    # 豆包必须关思考(闲聊17s→2.5s); 小米/智谱/OpenRouter 不传此参数
    if not _has_image(messages) and "doubao" in model:
        body["thinking"] = {"type": "disabled"}
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
            if not _has_image(messages) and "doubao" in model:
                body["thinking"] = {"type": "disabled"}
            elif "thinking" in body:
                del body["thinking"]
            # 注入额外 system 提示（如“禁用客服腔”）
            if fb.get("extra_system") and not tools:
                body["messages"] = [{"role": "system", "content": fb["extra_system"]}] + body["messages"]
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

    # 非工具调用时，过滤掉“收到/马上处理/好的稍等”等客服腔
    if not tools and isinstance(msg.get("content"), str):
        bad = ("收到", "马上处理", "好的稍等", "马上安排", "正在为您", "正在处理")
        content = msg["content"]
        for b in bad:
            if b in content:
                content = content.replace(b, "")
                print(f"[过滤] 移除客服腔: {b}")
        msg["content"] = content.strip()
    return msg


def call_glm(messages, max_tokens=800, temperature=0.5, retries=2):
    """直连智谱 GLM-4.5-flash(免费档): 给记忆摘要等低要求后台任务用, 不烧主模型配额

    成功返回 message dict; 未配 key 或重试后仍失败返回 None, 调用方自行降级主模型。
    """
    zc = _zhipu_config()
    if not zc:
        return None
    body = {"model": zc["model"], "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature,
            "thinking": {"type": "disabled"}}  # GLM-4.5 是思考模型, 后台杂活不需要思考, 防止 token 被思考耗光返回空
    api_url = f"{zc['base'].rstrip('/')}/chat/completions"
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                api_url,
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {zc['key']}"},
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            eb = ""
            try:
                eb = e.read().decode("utf-8", "ignore")[:200]
            except Exception:
                pass
            print(f"[GLM] HTTP {e.code}: {eb}")
            if e.code == 429 and attempt < retries:
                time.sleep(5 + attempt * 10)  # 免费档限流, 退避重试
                continue
        except Exception as e:
            print(f"[GLM-EXC] {e!r}")
            if attempt < retries:
                time.sleep(2 + attempt * 3)
                continue
    return None