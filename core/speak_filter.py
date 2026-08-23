"""TTS 可念性过滤: 剔除代码块/路径/JSON/base64/长数字串等非人话内容"""
import re
import base64


# 预编译正则
_CODE_BLOCK = re.compile(r'```[\s\S]*?```')
_INLINE_CODE = re.compile(r'`[^`\n]{2,}`')
_PATH_WIN = re.compile(r'[A-Za-z]:\\[^\s*?"<>|]{3,}')        # C:\foo\bar
_PATH_UNIX = re.compile(r'(?:~|/\w+)(?:/\w+)+')                # /home/user/foo
_JSON_LIKE = re.compile(r'\{[\s\S]{50,}?\}')                   # 长 JSON
_BASE64_LONG = re.compile(r'[A-Za-z0-9+/=]{100,}')            # 长 base64
_HEX_LONG = re.compile(r'0x[0-9a-fA-F]{20,}')                  # 长十六进制
_URL = re.compile(r'https?://[^\s]{30,}')                      # 长 URL
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_LONG_NUM = re.compile(r'\b\d{15,}\b')                         # 15+ 位数字


def speak_filter(text: str) -> str:
    """TTS 前过滤: 返回适合朗读的纯文本"""
    if not text:
        return text
    t = text
    # 1. 代码块 → 摘要
    t = _CODE_BLOCK.sub('（代码片段已省略）', t)
    # 2. 行内代码 → 去反引号
    t = _INLINE_CODE.sub(lambda m: m.group(0).strip('`'), t)
    # 3. 路径 → 简化
    t = _PATH_WIN.sub('（本地路径）', t)
    t = _PATH_UNIX.sub('（路径）', t)
    # 4. JSON / 大对象 → 摘要
    t = _JSON_LIKE.sub('（数据对象已省略）', t)
    # 5. 长 base64 / hex
    t = _BASE64_LONG.sub('（编码内容已省略）', t)
    t = _HEX_LONG.sub('（十六进制已省略）', t)
    # 6. 长 URL
    t = _URL.sub('（链接已省略）', t)
    # 7. UUID
    t = _UUID.sub('（标识符）', t)
    # 8. 超长数字串
    t = _LONG_NUM.sub('（长数字）', t)
    # 9. markdown 符号（复用 clean_reply 逻辑）
    t = re.sub(r'\*\*(.+?)\*\*', r'\1', t)
    t = re.sub(r'\*([^*\n]+?)\*', r'\1', t)
    t = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'\[([^\]]*)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'^#{1,6}\s*', '', t, flags=re.M)
    t = re.sub(r'^>\s?', '', t, flags=re.M)
    t = re.sub(r'^\s*[-*+]\s+', '。', t, flags=re.M)
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()