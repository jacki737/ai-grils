"""全网比价工具(v2: 帮你打开) —— 把比价页面直接开到浏览器里, 比价交给人眼

背景(诚实记录): v1 尝试 HTTP 直抓京东, 实测被风控(HTTP 直连只回 SPA 壳, Playwright
真渲染也不吐数据, 聚合站(购物党/什么值得买/慢慢买)对脚本客户端同样拦截)。继续硬抓
只会换来封号, 所以 v2 不再解析任何数据 —— 只负责导航: 把京东搜索页 + 购物党全网比价
页开到用户的浏览器里, 用户(或贾维斯后续读屏)看真实价格。行为和用户自己开网页一致,
永不触发风控, 且天然带用户登录态(能看到券后价)。

对外接口:
    def search_price(keyword: str) -> dict
        # {"ok": True, "msg": 口语播报, "data": {"pages": [{name, url, opened}]}}
"""

import threading
import urllib.parse

# 比价目标页: name 用于播报, url 的 {} 会被换成 urlencoded 关键词
_TARGETS = [
    {"name": "京东", "url": "https://search.jd.com/Search?keyword={}&enc=utf-8"},
    {"name": "购物党全网比价", "url": "https://www.gwdang.com/search/product?keyword={}"},
]

# 自起浏览器的引用(模块级, 保证 search_price 返回后窗口不消失, 用户手动关)
_OWN = {"pw": None, "browser": None}


def _open_url(url):
    """在浏览器打开 url。优先复用 browser.py 的全局浏览器(开新标签页, 不打扰
    当前会话页面); 没有可复用的就自己起一个真 Chrome 窗口(常驻)。
    返回 (ok, err)。"""
    # 1) 复用全局浏览器(playwright 对象不能跨线程, 必须同线程才安全)
    try:
        from .browser import _browser_singleton
        b = _browser_singleton.get("browser")
        if b is not None and _browser_singleton.get("thread") is threading.current_thread():
            pg = b.new_page()
            pg.goto(url, timeout=30000, wait_until="domcontentloaded")
            return True, None
    except Exception:
        pass
    # 2) 自己起一个常驻真 Chrome(有头); 引用挂在模块级防止被回收
    try:
        from playwright.sync_api import sync_playwright
        if _OWN["browser"] is None:
            _OWN["pw"] = sync_playwright().start()
            # 逐级回退: 真 Chrome → Edge(Windows 自带) → Playwright 自带 Chromium
            for channel in ("chrome", "msedge", None):
                try:
                    if channel:
                        _OWN["browser"] = _OWN["pw"].chromium.launch(
                            headless=False, channel=channel)
                    else:
                        _OWN["browser"] = _OWN["pw"].chromium.launch(headless=False)
                    break
                except Exception:
                    _OWN["browser"] = None
        pg = _OWN["browser"].new_page()
        pg.goto(url, timeout=30000, wait_until="domcontentloaded")
        return True, None
    except Exception as e:
        return False, str(e)


def search_price(keyword: str):
    """把『keyword』的京东搜索页 + 购物党全网比价页打开到浏览器, 供用户直接比价。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"ok": False, "error": "商品关键词不能为空"}

    pages, opened = [], []
    for t in _TARGETS:
        url = t["url"].format(urllib.parse.quote(keyword))
        ok, err = _open_url(url)
        pages.append({"name": t["name"], "url": url, "opened": ok})
        if ok:
            opened.append(t["name"])

    if not opened:
        errs = "; ".join(str(p) for p in pages if not p["opened"])
        return {"ok": False, "error": "浏览器打开失败: %s" % errs}

    msg = "已经把『%s』的%s页面打开到浏览器里了, 眼睛扫一眼就知道哪家最便宜" % (
        keyword, "和".join(opened))
    return {"ok": True, "msg": msg, "data": {"keyword": keyword, "pages": pages}}


if __name__ == "__main__":
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else "戴森v8"
    print(__doc__.strip()[:80])
    print("注意: 自测会弹出真实浏览器窗口")
    print(search_price(kw))
