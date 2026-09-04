"""12306 火车票余票查询工具 —— 直连 12306 公开查询接口, 无需登录

对外接口:
    def query_trains(from_city: str, to_city: str, date: str = "今天", top: int = 8) -> dict
        # {"ok": True, "msg": 口语播报, "data": {...}}

数据源:
    站点码表: https://kyfw.12306.cn/otn/resources/js/framework/station_name.js
    余票查询: https://kyfw.12306.cn/otn/leftTicket/queryZ (接口名会轮换, 备选 query/queryG/queryA)

注意: 只查询不下单。购票涉及实名+支付+滑块验证, 由用户拿着 data 里附带的
12306 链接自行完成, 工具不做任何登录态操作。
"""

import datetime
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request

_STATION_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"
_INIT_URL = "https://kyfw.12306.cn/otn/leftTicket/init"
_LEFT_TICKET_URL = "https://kyfw.12306.cn/otn/leftTicket/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 余票字符串列位 -> 席别名(12306 通用列位映射, 只展示有余票的列)
_SEAT_COLS = [
    (32, "商务座"), (31, "一等座"), (30, "二等座"),
    (28, "硬卧"), (29, "硬座"), (23, "软卧"), (21, "高级软卧"),
    (24, "动卧"), (26, "无座"),
]

_stations_cache = None  # {名称(站名/城市名/简拼): 电报码}, 进程内缓存
_opener = None          # 带 cookie 的 opener, init 和 query 复用同一份 cookie


def _get_opener():
    """懒加载带 CookieJar 的 opener: 先访问 init 页拿到会话 cookie, 后续查询才不被拒"""
    global _opener
    if _opener is None:
        jar = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(_INIT_URL, headers={
            "User-Agent": _UA,
            "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
        })
        _opener.open(req, timeout=15).read()
    return _opener


def _load_stations():
    """拉取并解析 12306 全量站点码表, 进程内缓存一次"""
    global _stations_cache
    if _stations_cache is not None:
        return _stations_cache
    req = urllib.request.Request(_STATION_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode("utf-8", "ignore")
    stations = {}
    # 每条格式: bjb|北京北|VAP|beijingbei|bjb|0|...  取 站名/城市名/全拼/简拼 当别名
    for entry in raw.split("@"):
        f = entry.split("|")
        if len(f) < 7 or not f[2]:
            continue
        code = f[2]
        stations[f[1]] = code                      # 站名, 如 上海虹桥
        if len(f) > 6 and f[6]:
            stations.setdefault(f[6], code)        # 城市名, 如 上海
        if len(f) > 3 and f[3]:
            stations.setdefault(f[3].lower(), code)  # 全拼, 如 shanghaihongqiao
        if f[0]:
            stations.setdefault(f[0].lower(), code)  # 简拼, 如 shhq
    _stations_cache = stations
    return stations


def _resolve_station(name):
    """中文站名/城市名/拼音 -> 电报码; 找不到给口语化报错"""
    stations = _load_stations()
    key = (name or "").strip()
    code = stations.get(key) or stations.get(key.lower())
    if code:
        return code
    # 模糊兜底: 用户传"北京南"但码表只有精确名时, 试包含匹配
    hits = [v for k, v in stations.items() if key and (key in k or k in key) and len(k) >= 2]
    if hits:
        return hits[0]
    raise RuntimeError("不认识的城市/站名: " + name)


def _resolve_date(text):
    """'今天/明天/后天/大后天/2026-08-31/8月31日' -> 12306 要的 YYYY-MM-DD"""
    text = (text or "今天").strip()
    today = datetime.date.today()
    offsets = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}
    if text in offsets:
        return (today + datetime.timedelta(days=offsets[text])).isoformat()
    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", text)
    if m:
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    else:
        m = re.search(r"(\d{1,2})[-/月.](\d{1,2})日?$", text)
        if m:
            d = datetime.date(today.year, int(m.group(1)), int(m.group(2)))
            if d < today:  # 没写年份的过去日期当成明年
                d = d.replace(year=today.year + 1)
        else:
            d = today
    return d.isoformat()


def _query_tickets(date, from_code, to_code):
    """调 12306 余票接口, 接口名轮换时自动换下一个重试"""
    opener = _get_opener()
    params = urllib.parse.urlencode({
        "leftTicketDTO.train_date": date,
        "leftTicketDTO.from_station": from_code,
        "leftTicketDTO.to_station": to_code,
        "purpose_codes": "ADULT",
    })
    last_err = None
    for ep in ("queryZ", "query", "queryG", "queryA"):
        try:
            req = urllib.request.Request(
                _LEFT_TICKET_URL + ep + "?" + params,
                headers={
                    "User-Agent": _UA,
                    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
                    "Accept": "application/json",
                })
            with opener.open(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            result = (data.get("data") or {})
            if isinstance(result.get("result"), list):
                return result.get("result") or [], result.get("map") or {}
        except Exception as e:
            last_err = e
    raise RuntimeError("12306 查询失败: %s" % last_err)


def _pick_seats(parts):
    """从余票字符串里挑出还有票的席别, 返回 [(席别, 数量/有)]"""
    seats = []
    for idx, label in _SEAT_COLS:
        v = parts[idx] if idx < len(parts) else ""
        v = v.strip()
        if v and v not in ("--", "无", ""):
            seats.append((label, v))
    return seats


def query_trains(from_city: str, to_city: str, date: str = "今天", top: int = 8):
    """查 12306 余票。from_city/to_city 支持城市名或站名, date 支持 今天/明天/后天 或具体日期。"""
    from_city = (from_city or "").strip()
    to_city = (to_city or "").strip()
    if not from_city or not to_city:
        return {"ok": False, "error": "出发地和目的地都不能为空"}
    top = max(1, min(int(top or 8), 15))

    date_iso = _resolve_date(date)
    from_code = _resolve_station(from_city)
    to_code = _resolve_station(to_city)
    rows, name_map = _query_tickets(date_iso, from_code, to_code)

    trains = []
    for row in rows:
        parts = row.split("|")
        if len(parts) < 33 or not parts[3]:
            continue
        seats = _pick_seats(parts)
        trains.append({
            "train_no": parts[3],                        # 车次, 如 G2
            "from_station": name_map.get(parts[6], parts[6]),
            "to_station": name_map.get(parts[7], parts[7]),
            "depart": parts[8],                          # 出发时间
            "arrive": parts[9],                          # 到达时间
            "duration": parts[10],                       # 历时, 如 04:29
            "can_buy": parts[11] == "Y",                 # 能否网购
            "seats": seats,
            "book_url": ("https://kyfw.12306.cn/otn/leftTicket/init"
                         "?linktypeid=dc&fs=%s,%s&ts=%s,%s&date=%s&flag=N,N,Y"
                         % (urllib.parse.quote(name_map.get(parts[6], from_city)),
                            parts[6],
                            urllib.parse.quote(name_map.get(parts[7], to_city)),
                            parts[7], date_iso)),
        })

    if not trains:
        return {"ok": True, "msg": "查到 %s到%s %s 的车次列表是空的, 日期没超过预售期吧?"
                                       % (from_city, to_city, date_iso),
                "data": {"date": date_iso, "count": 0, "trains": []}}

    # 有票的排前面, 同状态按出发时间
    trains.sort(key=lambda t: (not (t["can_buy"] and t["seats"]), t["depart"]))
    shown = trains[:top]

    segs = ["查到%s到%s %s 共%d趟车" % (from_city, to_city, date_iso, len(trains))]
    for t in shown:
        seat_desc = "/".join("%s%s" % (s[0], "有" if s[1] == "有" else s[1] + "张")
                             for s in t["seats"][:3]) if t["seats"] else "无票"
        mark = "" if t["can_buy"] else "(不可购)"
        segs.append("%s %s发%s到 %s %s%s"
                    % (t["train_no"], t["depart"], t["arrive"], t["duration"], seat_desc, mark))
    msg = "; ".join(segs) + "。"

    return {"ok": True, "msg": msg,
            "data": {"date": date_iso, "from": from_city, "to": to_city,
                     "count": len(trains), "trains": shown,
                     "book_url": shown[0]["book_url"]}}


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    res = query_trains(*args) if args else query_trains("北京", "上海", "明天")
    print(json.dumps(res, ensure_ascii=False, indent=2))
