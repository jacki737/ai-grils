"""主动闸门: 安静时段 / 速率限制 / 打扰控制

所有参数可在 config.json 的 "proactive" 段配置, 例:
"proactive": {
    "enabled": true,            // 总开关, false = 彻底不主动开口
    "quiet_hours": [23, 8],     // 安静时段 23:00-08:00
    "rate_limit_minutes": 60,   // 同一话题最少间隔(分钟)
    "max_per_hour": 1,          // 每小时主动开口上限
    "max_per_day": 5            // 每天主动开口上限
}
"""
import json
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

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"

# 默认值(收紧版, config.json 可覆盖)
_DEFAULTS = {
    "enabled": True,
    "quiet_hours": [23, 8],
    "rate_limit_minutes": 60,
    "max_per_hour": 1,
    "max_per_day": 5,
}
_cfg_cache = {"mtime": 0.0, "cfg": dict(_DEFAULTS)}


def _load_cfg() -> dict:
    """读 config.json 的 proactive 段(带 mtime 缓存, 改配置立即生效不用重启)"""
    try:
        mtime = _CONFIG_FILE.stat().st_mtime
    except Exception:
        return dict(_DEFAULTS)
    if _cfg_cache["mtime"] == mtime:
        return _cfg_cache["cfg"]
    cfg = dict(_DEFAULTS)
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        section = data.get("proactive") or {}
        if isinstance(section, dict):
            cfg.update({k: v for k, v in section.items() if k in _DEFAULTS})
    except Exception:
        pass
    _cfg_cache["mtime"] = mtime
    _cfg_cache["cfg"] = cfg
    return cfg


class ProactiveGate:
    """四重闸门: 总开关 / 安静时段 / 速率限制 / 每小时与每日上限"""

    def __init__(self):
        self._last_trigger = {}      # topic -> last_ts
        self._hourly_count = {}      # hour_key -> count
        self._daily_count = {}       # date_str -> count
        self._lock = threading.Lock()

    # ---------- 闸门 0: 总开关 ----------
    def _enabled(self) -> bool:
        return bool(_load_cfg().get("enabled", True))

    # ---------- 闸门 1: 安静时段 ----------
    def _in_quiet_hours(self) -> bool:
        start, end = _load_cfg().get("quiet_hours") or [23, 8]
        h = time.localtime().tm_hour
        if start > end:  # 跨午夜
            return h >= start or h < end
        return start <= h < end

    # ---------- 闸门 2: 速率限制 ----------
    def _rate_limited(self, topic: str) -> bool:
        now = time.time()
        limit_min = _load_cfg().get("rate_limit_minutes", 60)
        with self._lock:
            last = self._last_trigger.get(topic, 0)
            if now - last < limit_min * 60:
                return True
            return False

    def _mark_topic(self, topic: str):
        self._last_trigger[topic] = time.time()

    # ---------- 闸门 3: 每小时/每日上限 ----------
    def _quota_exceeded(self) -> bool:
        now = time.time()
        hour_key = int(now // 3600)
        day_key = time.strftime("%Y-%m-%d")
        cfg = _load_cfg()
        with self._lock:
            if self._hourly_count.get(hour_key, 0) >= cfg.get("max_per_hour", 1):
                return True
            if self._daily_count.get(day_key, 0) >= cfg.get("max_per_day", 5):
                return True
            return False

    def _mark_quota(self):
        hour_key = int(time.time() // 3600)
        day_key = time.strftime("%Y-%m-%d")
        with self._lock:
            self._hourly_count[hour_key] = self._hourly_count.get(hour_key, 0) + 1
            self._daily_count[day_key] = self._daily_count.get(day_key, 0) + 1
            # 只留最近 48 个小时桶和 7 天, 防止无限增长
            if len(self._hourly_count) > 48:
                for k in sorted(self._hourly_count)[:-48]:
                    self._hourly_count.pop(k, None)
            if len(self._daily_count) > 7:
                for k in sorted(self._daily_count)[:-7]:
                    self._daily_count.pop(k, None)

    # ---------- 闸门 4: 打扰控制 ----------
    def _user_busy(self) -> bool:
        """检测用户是否处于忙碌状态: 全屏应用 / 媒体播放"""
        if not WIN32_AVAILABLE:
            return False
        try:
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd:
                placement = win32gui.GetWindowPlacement(fg_hwnd)
                if placement[1] == 3:  # SW_SHOWMAXIMIZED
                    return True
                rect = win32gui.GetWindowRect(fg_hwnd)
                import win32api
                screen_w = win32api.GetSystemMetrics(0)
                screen_h = win32api.GetSystemMetrics(1)
                if rect[2] - rect[0] >= screen_w and rect[3] - rect[1] >= screen_h:
                    return True

            for proc in psutil.process_iter(['name']):
                name = proc.info['name'].lower()
                if any(kw in name for kw in ('cloudmusic', 'netease', 'music', 'potplayer', 'vlc', 'wmplayer', 'spotify', 'qqmusic')):
                    return True
        except Exception:
            pass
        return False

    # ---------- 统一入口 ----------
    def allow(self, topic: str = "default") -> tuple[bool, str]:
        """返回 (是否允许, 拒绝原因)。允许时内部自动计数(成功说出才算一次)。"""
        if not self._enabled():
            return False, "主动开关已关闭"
        if self._in_quiet_hours():
            return False, "安静时段"
        if self._rate_limited(topic):
            limit = _load_cfg().get("rate_limit_minutes", 60)
            return False, f"速率限制({limit}分钟)"
        if self._quota_exceeded():
            return False, "每小时/每日上限"
        if self._user_busy():
            return False, "用户忙碌"
        self._mark_topic(topic)
        self._mark_quota()
        return True, ""


# 单例
_gate = ProactiveGate()


def proactive_allowed(topic: str = "default") -> tuple[bool, str]:
    """外部调用入口"""
    return _gate.allow(topic)


def set_quiet_hours(start: int, end: int):
    _update_config(quiet_hours=[start, end])


def set_rate_limit(seconds: int):
    _update_config(rate_limit_minutes=max(1, seconds // 60))


def set_max_per_hour(n: int):
    _update_config(max_per_hour=n)


def _update_config(**kw):
    """把运行时修改写回 config.json(持久化, 重启不丢)"""
    try:
        data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8")) if _CONFIG_FILE.exists() else {}
        section = data.get("proactive") or {}
        if "quiet_hours" in kw:
            section["quiet_hours"] = kw["quiet_hours"]
        if "rate_limit_minutes" in kw:
            section["rate_limit_minutes"] = kw["rate_limit_minutes"]
        if "max_per_hour" in kw:
            section["max_per_hour"] = kw["max_per_hour"]
        data["proactive"] = section
        _CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
