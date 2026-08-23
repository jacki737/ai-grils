"""语音合成: CosyVoice / Edge-TTS / 小米 MiMo TTS 三通道 (async)"""
import json
import time
import aiohttp
import asyncio
from pathlib import Path


def load_config():
    p = Path(__file__).parent.parent.parent / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


async def _cosyvoice_synthesize(text: str, voice_id: str = "cosyvoice:default") -> bytes:
    """CosyVoice 合成 (async) - 占位"""
    raise NotImplementedError("CosyVoice 未接入")


async def _edge_tts_synthesize(text: str, voice: str = "zh-CN-XiaoxiaoNeural") -> bytes:
    """Edge TTS 合成 (async) - 通过 edge-tts CLI"""
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
    """小米 MiMo TTS (async)"""
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
    """根据角色配置选择 TTS 通道 (async)"""
    # 简化: 默认走 Edge TTS
    return await _edge_tts_synthesize(text)