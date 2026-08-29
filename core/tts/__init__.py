"""语音合成: Audio8-TTS (本地 ONNX CPU) 为主, 百度/Edge-TTS 兜底"""
import json
import time
import aiohttp
import asyncio
import base64
import hashlib
import hmac
import logging
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIO8_TTS_BASE = "http://127.0.0.1:8024"


def load_config():
    p = Path(__file__).parent.parent.parent / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def _audio8_tts_synthesize(text: str, voice: str = "speaker_a") -> bytes:
    """Audio8-TTS 本地推理 (OpenAI 兼容 /v1/audio/speech)"""
    url = f"{AUDIO8_TTS_BASE}/v1/audio/speech"
    body = {"model": "arktts", "input": text, "voice": voice, "response_format": "wav"}
    headers = {"Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                data = await r.json()
                raise RuntimeError(f"Audio8-TTS {r.status}: {json.dumps(data, ensure_ascii=False)[:200]}")
            return await r.read()


async def _baidu_tts_synthesize(text: str, voice: int = 0) -> bytes:
    """百度云语音合成 (REST API, 需先获取 access_token)"""
    cfg = load_config()
    app_id = cfg.get("baidu_app_id") or "7965794"
    api_key = cfg.get("baidu_api_key") or "FwcSekXiHGE9h2RtYTvFj72O"
    secret_key = cfg.get("baidu_secret_key") or "R8SxpowFMkbnjxQFPt99ouUmpMSMj12r"
    
    # 获取 access_token (缓存 30 天)
    token_key = f"baidu_token_{api_key}"
    token_cache = getattr(_baidu_tts_synthesize, "token_cache", {})
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
                    raise RuntimeError(f"百度获取 token 失败: {data}")
                access_token = data["access_token"]
                token_cache[token_key] = {"token": access_token, "expires": now + 25 * 24 * 3600}
                _baidu_tts_synthesize.token_cache = token_cache
    
    # 合成语音
    tts_url = "https://tsn.baidu.com/text2audio"
    params = {
        "tex": text,
        "tok": access_token,
        "cuid": f"ai-girlfriend-{app_id}",
        "ctp": 1,
        "lan": "zh",
        "spd": 5,  # 语速 0-15
        "pit": 5,  # 音调 0-15
        "vol": 5,  # 音量 0-15
        "per": voice,  # 发音人: 0=度小美, 1=度小宇, 3=度逍遥, 4=度丫丫, 5=度小娇, 103=度米朵, 106=度博文, 110=度小童, 111=度小萌
        "aue": 6,  # 6=wav
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(tts_url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                raise RuntimeError(f"百度 TTS HTTP {r.status}")
            content_type = r.headers.get("Content-Type", "")
            if "audio" not in content_type and "application/json" in content_type:
                err = await r.json()
                raise RuntimeError(f"百度 TTS 错误: {err}")
            return await r.read()


async def _qwen_tts_synthesize(text: str, voice: str = "Cherry") -> bytes:
    """阿里 qwen3-tts-flash 合成 (DashScope 标准 TTS API)"""
    cfg = load_config()
    key = (cfg.get("dashscope_asr_key") or cfg.get("dashscope_key") or "").strip()
    if not key:
        raise RuntimeError("DashScope key 未配置")
    url = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts"
    # 尝试不同 payload 格式
    payloads = [
        {"model": "qwen3-tts-flash", "input": text, "voice": voice, "response_format": "wav"},
        {"model": "qwen3-tts-flash", "text": text, "voice": voice, "format": "wav"},
        {"model": "qwen3-tts-flash", "text": text, "voice": voice},
    ]
    last_err = None
    for body in payloads:
        try:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status != 200:
                        data = await r.json()
                        raise RuntimeError(f"qwen3-tts-flash {r.status}: {json.dumps(data, ensure_ascii=False)[:200]}")
                    return await r.read()
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("qwen3-tts-flash 所有 payload 均失败")


async def _edge_tts_synthesize(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> bytes:
    """Edge TTS 合成 (通过 edge-tts CLI)"""
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "edge-tts", "--voice", voice, "--text", text, "--write-media", tmp_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.wait()
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


async def _xiaoai_tts(text: str, voice: str = "冰糖", style: str = "") -> bytes:
    """小米 MiMo TTS"""
    cfg = load_config()
    key = (cfg.get("mimo_key") or "").strip()
    if not key:
        raise RuntimeError("MiMo key 缺失")
    base = "https://api.xiaomimimo.com/v1"
    url = f"{base}/audio/speech"
    body = {"model": "mimo-tts", "input": text, "voice": voice, "style": style}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            return await r.read()


async def synthesize(text: str, role: str = "jarvis") -> bytes:
    """Audio8-TTS 为主 (本地 ONNX CPU), 失败降级百度/Edge-TTS"""
    # 角色 -> Audio8-TTS 已注册的 voice name
    audio8_voice_map = {
        "jarvis": "speaker_a",
        "girlfriend": "speaker_gf",
        "selis": "speaker_gf",
        "yujie": "speaker_gf",
        "taiwan": "speaker_gf",
        "xiaohu": "speaker_a",
        "krab": "speaker_a",
        "plankton": "speaker_a",
        "pilaoban": "speaker_a",
    }
    # 角色 -> 百度发音人映射 (降级用)
    baidu_voice_map = {
        "jarvis": 106, "girlfriend": 0, "selis": 111, "yujie": 4,
        "taiwan": 5, "xiaohu": 1, "krab": 106, "plankton": 1, "pilaoban": 106,
    }
    # 角色 -> Edge-TTS 声音映射 (降级用)
    edge_voice_map = {
        "jarvis": "zh-CN-YunjianNeural",
        "girlfriend": "zh-CN-XiaoxiaoNeural",
        "selis": "zh-CN-XiaoyiNeural",
        "yujie": "zh-CN-YunjianNeural",
        "taiwan": "zh-TW-HsiaoChenNeural",
        "xiaohu": "zh-CN-YunxiNeural",
        "krab": "zh-CN-YunxiNeural",
        "plankton": "zh-CN-YunxiNeural",
        "pilaoban": "zh-CN-YunjianNeural",
    }

    audio8_voice = audio8_voice_map.get(role, "speaker_a")
    baidu_voice = baidu_voice_map.get(role, 106)
    edge_voice = edge_voice_map.get(role, "zh-CN-XiaoxiaoNeural")

    # 1. Audio8-TTS (本地首选)
    try:
        audio = await _audio8_tts_synthesize(text, audio8_voice)
        logger.info(f"[TTS] Audio8-TTS 成功 ({len(audio)} bytes)")
        return audio
    except Exception as e:
        logger.warning(f"[TTS] Audio8-TTS 失败({e}), 降级百度 TTS")

    # 2. 百度 TTS
    try:
        audio = await _baidu_tts_synthesize(text, baidu_voice)
        logger.info(f"[TTS] 百度 TTS 成功 ({len(audio)} bytes)")
        return audio
    except Exception as e:
        logger.warning(f"[TTS] 百度 TTS 失败({e}), 降级 Edge-TTS")

    # 3. Edge-TTS
    try:
        audio = await _edge_tts_synthesize(text, edge_voice)
        logger.info(f"[TTS] Edge-TTS 成功 ({len(audio)} bytes)")
        return audio
    except Exception as e:
        logger.warning(f"[TTS] Edge-TTS 失败({e})")
        raise