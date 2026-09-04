import asyncio
import sys
sys.path.insert(0, '.')
from core.stt import transcribe
import struct

sr = 16000
samples = b'\x00\x00' * int(sr * 0.5)
wav = b'RIFF' + struct.pack('<I', 36 + len(samples)) + b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 1, 1, sr, sr*2, 2, 16) + b'data' + struct.pack('<I', len(samples)) + samples

async def test():
    print('=== Full transcribe (with local fallback) ===')
    try: 
        result = await transcribe(wav)
        print(f'Result: {result}')
    except Exception as e: 
        print('ERROR:', e)

asyncio.run(test())