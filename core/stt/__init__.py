"""语音识别: 小米 MiMo 优先(最快最稳), 百度/阿里 DashScope 兜底"""
import json
import time
import aiohttp
import base64
import logging
from pathlib import Path
from logsetup import setup_logging
setup_logging()

logger = logging.getLogger(__name__)


def load_config():
    p = Path(__file__).parent.parent.parent / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _detect_audio_format(audio_bytes: bytes) -> str:
    if audio_bytes[:4] == b"RIFF":
        return "wav"
    if audio_bytes[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb" or audio_bytes[:2] == b"\xff\xf3":
        return "mp3"
    return "wav"


def _extract_pcm(audio_bytes: bytes) -> bytes:
    """去掉 WAV 头部，返回原始 PCM 数据"""
    if audio_bytes[:4] == b"RIFF":
        # WAV 头部通常 44 字节，跳过到 data chunk
        # 简单处理：找到 "data" 标识后跳过 8 字节
        data_idx = audio_bytes.find(b"data")
        if data_idx != -1:
            return audio_bytes[data_idx + 8:]
    return audio_bytes


async def _baidu_asr_transcribe(audio_bytes: bytes) -> str:
    """百度短语音识别 (REST API, 需先获取 access_token)"""
    cfg = load_config()
    app_id = cfg.get("baidu_asr_app_id")
    api_key = cfg.get("baidu_asr_api_key")
    secret_key = cfg.get("baidu_asr_secret_key")

    # 获取 access_token (缓存 30 天)
    token_key = f"baidu_asr_token_{api_key}"
    token_cache = getattr(_baidu_asr_transcribe, "token_cache", {})
    now = time.time()
    if token_key in token_cache and token_cache[token_key]["expires"] > now:
        access_token = token_cache[token_key]["token"]
    else:
        token_url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": secret_key,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                if "access_token" not in data:
                    raise RuntimeError(f"百度 ASR 获取 token 失败: {data}")
                access_token = data["access_token"]
                token_cache[token_key] = {"token": access_token, "expires": now + 25 * 24 * 3600}
                _baidu_asr_transcribe.token_cache = token_cache

    # 语音识别 (短语音识别极速版, dev_pid=80001) - 使用 server_api 接口 (支持 wav/mp3/webm)
    fmt = _detect_audio_format(audio_bytes)
    format_map = {"wav": "wav", "mp3": "mp3", "webm": "webm"}
    audio_format = format_map.get(fmt, "wav")

    asr_url = "https://vop.baidu.com/server_api"
    b64 = base64.b64encode(audio_bytes).decode()
    body = {
        "format": audio_format,
        "rate": 16000,
        "channel": 1,
        "cuid": f"ai-girlfriend-{app_id}",
        "token": access_token,
        "speech": b64,
        "len": len(audio_bytes),
        "dev_pid": 80001,  # 极速版, 支持中英混合
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(asr_url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as r:
            data = await r.json()
            if data.get("err_no") != 0:
                raise RuntimeError(f"百度 ASR 失败: {data}")
    return (data.get("result") or [""])[0].strip()


async def _dashscope_asr_transcribe(audio_bytes: bytes) -> str:
    """阿里 DashScope ASR (qwen3-asr-flash 兼容模式, 同步 HTTP, 支持 webm/wav/mp3)"""
    cfg = load_config()
    key = (cfg.get("dashscope_asr_key") or "").strip()
    if not key:
        raise RuntimeError("DashScope ASR key 未配置")
    b64 = base64.b64encode(audio_bytes).decode()
    fmt = _detect_audio_format(audio_bytes)
    data_uri = f"data:audio/{fmt};base64,{b64}"
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    body = {
        "model": "qwen3-asr-flash",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "input_audio", "input_audio": {"data": data_uri, "format": fmt}},
            ],
        }],
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
            data = await r.json()
            if r.status != 200:
                raise RuntimeError(f"DashScope ASR {r.status}: {json.dumps(data, ensure_ascii=False)[:200]}")
    msg = ((data.get("choices") or [{}])[0].get("message") or {})
    return (msg.get("content") or "").strip()


async def _mimo_asr_transcribe(audio_bytes: bytes) -> str:
    """小米 MiMo ASR (mimo-v2.5-asr, chat/completions + input_audio)"""
    cfg = load_config()
    key = (cfg.get("mimo_key") or "").strip()
    if not key:
        raise RuntimeError("MiMo key 未配置")
    base = "https://api.xiaomimimo.com/v1"
    b64 = base64.b64encode(audio_bytes).decode()
    fmt = _detect_audio_format(audio_bytes)
    # MiMo 仅支持 wav/mp3/mpeg，浏览器常发 webm -> 映射为 mp3
    mimo_fmt = "mp3" if fmt == "webm" else fmt
    data_uri = f"data:audio/{mimo_fmt};base64,{b64}"
    url = f"{base}/chat/completions"
    body = {
        "model": "mimo-v2.5-asr",
        "messages": [{
            "role": "user",
            "content": [{
                "type": "input_audio",
                "input_audio": {"data": data_uri, "format": mimo_fmt},
            }],
        }],
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
            data = await r.json()
            if r.status != 200:
                raise RuntimeError(f"MiMo ASR {r.status}: {json.dumps(data, ensure_ascii=False)[:200]}")
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _valid_text(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if len(t) < 2:
        return False
    import re
    if re.match(r'^[\s\W\d_]+$', t):
        return False
    if len(set(t)) == 1:
        return False
    non_alpha = sum(1 for c in t if not ('\u4e00' <= c <= '\u9fff' or c.isascii()))
    if non_alpha / len(t) > 0.5:
        return False
    silence_hallucinations = {
        '嗯', '啊', '哦', '诶', '唔', '哈', '呵', '哼', '呀', '啦',
        '嗯。', '啊。', '哦。', '诶。', '嗯嗯', '啊啊', '哦哦',
        '的。', '了。', '是。', '在。', '有。', '我。', '你。', '它。',
        '吧。', '呢。', '吗。', '哈。', '呵。', '呸。', '啸。'
    }
    if t in silence_hallucinations:
        return False
    if len(t) == 2 and '\u4e00' <= t[0] <= '\u9fff' and t[1] in '。！？.!?':
        return False
    return True


async def transcribe(audio_bytes: bytes) -> str:
    """MiMo ASR 优先(实测最快最稳) → 百度 → DashScope
    (百度 3302 无权限 / DashScope 欠费, 每句空跑 ~1.5s, 故降为兜底)"""
    t0 = time.time()
    # 1. MiMo ASR
    try:
        text = await _mimo_asr_transcribe(audio_bytes)
        logger.info(f"[STT] MiMo ASR: {text} ({time.time()-t0:.1f}s)")
        if _valid_text(text):
            return text
    except Exception as e:
        logger.warning(f"[STT] MiMo ASR 失败({e}), 降级百度")
    # 2. 百度 ASR
    try:
        text = await _baidu_asr_transcribe(audio_bytes)
        logger.info(f"[STT] 百度 ASR: {text} ({time.time()-t0:.1f}s)")
        if _valid_text(text):
            return text
    except Exception as e:
        logger.warning(f"[STT] 百度 ASR 失败({e}), 降级 DashScope")
    # # 3. DashScope
    # try:
    #     text = await _dashscope_asr_transcribe(audio_bytes)
    #     logger.info(f"[STT] DashScope ASR: {text} ({time.time()-t0:.1f}s)")
    #     if _valid_text(text):
    #         return text
    # except Exception as e:
    #     logger.warning(f"[STT] DashScope ASR 失败({e})")
    return "（语音识别暂不可用，请用文字聊天哦～）"