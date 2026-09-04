import asyncio
import sys
sys.path.insert(0, '.')
from core.stt import _volc_asr_transcribe, _mimo_asr_transcribe, _dashscope_asr_transcribe
import struct

sr = 16000
samples = b'\x00\x00' * int(sr * 0.5)
wav = b'RIFF' + struct.pack('<I', 36 + len(samples)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, sr, sr*2, 2, 16) + b'data' + struct.pack('<I', len(samples)) + samples

async def test():
    print('=== VolcEngine ===')
    try: print(await _volc_asr_transcribe(wav))
    except Exception as e: print('ERROR:', e)
    
    print('=== MiMo ===')
    try: print(await _mimo_asr_transcribe(wav))
    except Exception as e: print('ERROR:', e)
    
    print('=== DashScope ===')
    try: print(await _dashscope_asr_transcribe(wav))
    except Exception as e: print('ERROR:', e)

asyncio.run(test())