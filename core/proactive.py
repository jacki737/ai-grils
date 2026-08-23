"""主动闸门: 安静时段 / 速率限制 / 打扰控制"""
import time
import threading
from pathlib import Path

try:
    import win32gui
    import win32process
    import psutil
    WIN32_AVAILABLE = True
except Exception:
    WIN32_AVAILABLE = False


# 配置（可后续从 config.json 读取）
QUIET_HOURS_START = 23   # 23:00
QUIET_HOURS_END = 8      # 08:00
RATE_LIMIT_SECONDS = 30 * 60  # 30 分钟
MAX_PROACTIVE_PER_HOUR = 3    # 每小时最多主动开口次数


class ProactiveGate:
    """三重闸门：安静时段 / 速率限制 / 打扰控制"""

    def __init__(self):
        self._last_trigger = {}      # topic -> last_ts
        self._hourly_count = {}      # hour -> count
        self._lock = threading.Lock()

    # ---------- 闸门 1：安静时段 ----------
    def _in_quiet_hours(self) -> bool:
        h = time.localtime().tm_hour
        if QUIET_HOURS_START > QUIET_HOURS_END:  # 跨午夜
            return h >= QUIET_HOURS_START or h < QUIET_HOURS_END
        return QUIET_HOURS_START <= h < QUIET_HOURS_END

    # ---------- 闸门 2：速率限制 ----------
    def _rate_limited(self, topic: str) -> bool:
        now = time.time()
        with self._lock:
            last = self._last_trigger.get(topic, 0)
            if now - last < RATE_LIMIT_SECONDS:
                return True
            self._last_trigger[topic] = now
            return False

    # ---------- 闸门 3：每小时总量上限 ----------
    def _hourly_exceeded(self) -> bool:
        now = time.time()
        hour_key = int(now // 3600)
        with self._lock:
            cnt = self._hourly_count.get(hour_key, 0)
            if cnt >= MAX_PROACTIVE_PER_HOUR:
                return True
            self._hourly_count[hour_key] = cnt + 1
            return False

    # ---------- 闸门 4：打扰控制 ----------
    def _user_busy(self) -> bool:
        """检测用户是否处于忙碌状态：全屏应用 / 媒体播放 / 正在打字"""
        if not WIN32_AVAILABLE:
            return False
        try:
            # 1. 前台窗口全屏
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd:
                placement = win32gui.GetWindowPlacement(fg_hwnd)
                if placement[1] == 3:  # SW_SHOWMAXIMIZED
                    return True
                # 进一步判断是否为全屏独占（排除任务栏）
                rect = win32gui.GetWindowRect(fg_hwnd)
                import win32api
                screen_w = win32api.GetSystemMetrics(0)
                screen_h = win32api.GetSystemMetrics(1)
                if rect[2] - rect[0] >= screen_w and rect[3] - rect[1] >= screen_h:
                    return True

            # 2. 检测媒体播放进程（简单启发式：常见播放器进程名）
            for proc in psutil.process_iter(['name']):
                name = proc.info['name'].lower()
                if any(kw in name for kw in ('cloudmusic', 'netease', 'music', 'potplayer', 'vlc', 'wmplayer', 'spotify', 'qqmusic')):
                    # 进一步可检测音频会话是否活跃，这里简化直接返回
                    return True

        except Exception:
            pass
        return False

    # ---------- 统一入口 ----------
    def allow(self, topic: str = "default") -> tuple[bool, str]:
        """
        返回 (是否允许, 拒绝原因)
        """
        if self._in_quiet_hours():
            return False, "安静时段"
        if self._rate_limited(topic):
            return False, f"速率限制({RATE_LIMIT_SECONDS//60}分钟)"
        if self._hourly_exceeded():
            return False, f"每小时上限({MAX_PROACTIVE_PER_HOUR}次)"
        if self._user_busy():
            return False, "用户忙碌中"
        return True, ""


# 单例
_gate = ProactiveGate()


def proactive_allowed(topic: str = "default") -> tuple[bool, str]:
    """外部调用入口"""
    return _gate.allow(topic)


def set_quiet_hours(start: int, end: int):
    global QUIET_HOURS_START, QUIET_HOURS_END
    QUIET_HOURS_START = start
    QUIET_HOURS_END = end


def set_rate_limit(seconds: int):
    global RATE_LIMIT_SECONDS
    RATE_LIMIT_SECONDS = seconds


def set_max_per_hour(n: int):
    global MAX_PROACTIVE_PER_HOUR
    MAX_PROACTIVE_PER_HOUR = n