"""天气查询工具 —— 直连 wttr.in JSON API, 不走浏览器爬虫(实测天气站403/超时率高)

对外接口:
    def get_weather(city: str) -> dict   # {"ok": True, "msg": 口语播报, "data": {...}}
"""

import json
import urllib.parse
import urllib.request

# wttr.in 天气描述英文 → 中文(实测 lang=zh 字段不稳定, 本地映射兜底)
_DESC_ZH = {
    "clear": "晴", "sunny": "晴", "partly cloudy": "多云", "cloudy": "多云",
    "overcast": "阴", "mist": "薄雾", "fog": "雾", "haze": "霾", "smoke": "烟霾",
    "light drizzle": "毛毛雨", "drizzle": "毛毛雨", "patchy light drizzle": "零星毛毛雨",
    "light rain": "小雨", "moderate rain": "中雨", "heavy rain": "大雨",
    "light rain shower": "阵雨", "thundery outbreaks possible": "雷阵雨",
    "thunderstorm": "雷雨", "light snow": "小雪", "moderate snow": "中雪",
    "heavy snow": "大雪", "light sleet": "雨夹雪", "blizzard": "暴风雪",
    "freezing fog": "冻雾", "patchy rain possible": "可能有小雨",
    "sunny intervals": "间歇晴", "light showers": "小阵雨",
}


def get_weather(city: str = "北京"):
    """查城市天气。city 支持中文(如 北京/杭州)或拼音。返回 {ok, msg, data}。"""
    city = (city or "北京").strip() or "北京"
    url = ("https://wttr.in/" + urllib.parse.quote(city)
           + "?format=j1&lang=zh")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "curl/8.0",
            "Accept-Language": "zh-CN",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        cur = (data.get("current_condition") or [{}])[0]
        temp = cur.get("temp_C", "?")
        feels = cur.get("FeelsLikeC", "?")
        desc_zh = ""
        desc_en = ""
        langs = cur.get("lang_zh") or []
        if langs:
            desc_zh = (langs[0] or {}).get("value", "")
        weather_descs = cur.get("weatherDesc") or []
        if weather_descs:
            desc_en = (weather_descs[0] or {}).get("value", "")
        desc = desc_zh or desc_en or "未知"
        humidity = cur.get("humidity", "?")
        wind = cur.get("windspeedKmph", "?")

        # 今天/明天 预报
        forecast = []
        for day in (data.get("weather") or [])[:2]:
            date = day.get("date", "")
            tmin = day.get("mintempC", "?")
            tmax = day.get("maxtempC", "?")
            forecast.append((date, tmin, tmax))

        parts = [f"{city}现在{desc} 气温{temp}度 体感{feels}度"]
        if forecast:
            _, tmin, tmax = forecast[0]
            parts.append(f"今天{tmin}到{tmax}度")
            if len(forecast) > 1:
                _, tmin2, tmax2 = forecast[1]
                parts.append(f"明天{tmin2}到{tmax2}度")
        msg = " ".join(parts) + f" 湿度{humidity}%。"

        return {
            "ok": True,
            "msg": msg,
            "data": {
                "city": city, "desc": desc, "temp": temp, "feels": feels,
                "humidity": humidity, "wind_kmph": wind, "forecast": forecast,
            },
        }
    except Exception as e:
        return {"ok": False, "error": f"天气查询失败({city}): {e}"}


if __name__ == "__main__":
    import sys
    print(get_weather(sys.argv[1] if len(sys.argv) > 1 else "北京"))
