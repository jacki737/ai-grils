"""统一日志系统: logs/app.log + 控制台双输出"""
import io
import logging
import sys
from pathlib import Path

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_FILE = _LOG_DIR / "app.log"
_FMT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class _StreamToLog(io.TextIOBase):
    """把 print()/stdout/stderr 的写入实时转成日志行"""

    def __init__(self, emit):
        self._emit = emit
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                try:
                    self._emit(line)
                except Exception:
                    pass
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


def setup_logging():
    """初始化根 logger; 幂等, 重复调用无副作用"""
    _LOG_DIR.mkdir(exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_ai_gf_logging_ready", False):
        return root
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(_FMT)

    # 简单 FileHandler 不轮转, 避免锁死
    fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 控制台仍能看到
    sh = logging.StreamHandler(sys.__stderr__)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    # 接管 print/stdout/stderr
    sys.stdout = _StreamToLog(lambda m: logging.getLogger("stdout").info(m))
    sys.stderr = _StreamToLog(lambda m: logging.getLogger("stderr").error(m))

    # 第三方库降噪
    for noisy in ("urllib3", "httpx", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root._ai_gf_logging_ready = True
    root.info("[logsetup] 日志初始化完成 -> %s", _LOG_FILE)
    return root