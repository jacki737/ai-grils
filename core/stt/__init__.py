"""语音识别: DashScope ASR (qwen3-asr-flash) 为主, 小米 MiMo 兜底"""
import json
import time
import aiohttp
import base64
from pathlib import Path


def load_config():
    p = Path(__file__).parent.parent.parent / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _detect_audio_format(audio_bytes: bytes) -> str:
    """从字节头识别音频格式 (RIFF=wav, 1A45DFA3=webm, ID3/MPEG=mp3)"""
    if audio_bytes[:4] == b"RIFF":
        return "wav"
    if audio_bytes[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if audio_bytes[:3] == b"ID3" or audio_bytes[:2] == b"\xff\xfb" or audio_bytes[:2] == b"\xff\xf3":
        return "mp3"
    return "wav"


async def _dashscope_asr_transcribe(audio_bytes: bytes) -> str:
    """阿里 DashScope ASR (qwen3-asr-flash 兼容模式, 同步 HTTP, 支持 webm/wav/mp3)"""
    cfg = load_config()
    key = (cfg.get("dashscope_asr_key") or "").strip()
    if not key:
        raise RuntimeError("DashScope ASR key 未配置")
    b64 = base64.b64encode(audio_bytes).decode()
    fmt = _detect_audio_format(audio_bytes)
    # DashScope 兼容模式需要 data URI 格式
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
    """小米 MiMo ASR (async) - 兜底"""
    cfg = load_config()
    key = (cfg.get("mimo_key") or "").strip()
    if not key:
        raise RuntimeError("MiMo key 未配置")
    base = "https://api.xiaomimimo.com/v1"
    urls = [
        f"{base}/audio/transcriptions",
        f"{base}/v1/audio/transcriptions",
    ]
    b64 = base64.b64encode(audio_bytes).decode()
    fmt = _detect_audio_format(audio_bytes)
    body = {"model": "mimo-asr", "audio": f"data:audio/{fmt};base64,{b64}"}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get("text", "")
            except Exception:
                continue
    raise RuntimeError("MiMo ASR 所有 endpoint 均失败")


async def transcribe(audio_bytes: bytes) -> str:
    """优先 DashScope ASR, 失败再试 MiMo"""
    t0 = time.time()
    # 优先 DashScope (你配了 dashscope_asr_key)
    try:
        text = await _dashscope_asr_transcribe(audio_bytes)
        print(f"[STT] DashScope ASR: {text} ({time.time()-t0:.1f}s)")
        return text
    except Exception as e:
        print(f"[STT] DashScope 失败({e}), 降级 MiMo")
    # 兜底 MiMo
    try:
        text = await _mimo_asr_transcribe(audio_bytes)
        print(f"[STT] MiMo ASR: {text} ({time.time()-t0:.1f}s)")
        return text
    except Exception as e:
        print(f"[STT] MiMo 失败({e})")
        return "（语音识别暂不可用，请用文字聊天哦～）"