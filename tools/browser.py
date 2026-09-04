"""浏览器控制(Playwright 驱动 Chromium/Google Chrome)

用 Playwright 启动一个浏览器窗口(有头模式, 用户能看见), 支持打开网页/执行JS/
点击/输入/取文字/截图/后退/关闭。浏览器是全局单例(懒启动), 按线程复用。
依赖: pip install playwright && python3 -m playwright install chromium
"""
import os
import shutil
import threading

# 需要: pip install playwright && python3 -m playwright install chromium
# 系统依赖: sudo python3 -m playwright install-deps chromium
# 全局单例: browser/page/mode 跨多次调用复用; 每把操作锁定在一个线程里跑
# (playwright 对象不能跨线程使用, 所以用 thread 字段记录归属线程)。
_browser_singleton = {"browser": None, "page": None, "mode": "headless", "chrome": False, "pw": None, "thread": None}


def _find_chrome():
    """探测本机是否安装了真正的 Google Chrome(Windows/Linux 常见路径)"""
    if os.name == "nt":
        cands = [
            os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                         r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                         r"Google\Chrome\Application\chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         r"Google\Chrome\Application\chrome.exe"),
        ]
        return next((c for c in cands if c and os.path.isfile(c)), None)
    for cand in ("google-chrome", "google-chrome-stable",
                 "/usr/bin/google-chrome", "/opt/google/chrome/chrome"):
        if os.path.isfile(cand) or shutil.which(cand):
            return cand
    return None


def _get_page():
    """获取全局 playwright 页面(懒启动, 线程绑定: 换线程自动重建, 避免 greenlet 冲突)

    优先有头模式(headless=False): 弹出一个用户能看到的浏览器窗口,
    若本机装有 Google Chrome 则用 channel="chrome" 启动真正的 Chrome,
    未安装则回退默认 Chromium(同样是可见窗口);
    DISPLAY 为空或启动抛异常(无可用图形环境)时, 自动降级无头模式, 不崩溃。
    """
    cur = threading.current_thread()
    # 同线程且已建好 → 直接复用(playwright 对象不能跨线程使用)
    if _browser_singleton["page"] is not None and _browser_singleton.get("thread") is cur:
        return _browser_singleton["page"]
    # 换线程了 → 旧实例无法复用, 关掉后重新创建
    try:
        if _browser_singleton.get("browser") is not None:
            _browser_singleton["browser"].close()
    except Exception:
        pass
    _browser_singleton["browser"] = None
    _browser_singleton["page"] = None
    _browser_singleton["thread"] = cur

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    # 探测显示环境: Windows 桌面始终有头; Linux 看 DISPLAY
    mode = "headful" if (os.name == "nt" or os.environ.get("DISPLAY")) else "headless"
    used_chrome = False
    browser = None
    if mode == "headful":
        try:
            # 有头模式: 优先真正的 Google Chrome, 可见窗口 + 1280x800
            if _find_chrome():
                browser = pw.chromium.launch(
                    headless=False, channel="chrome",
                    args=["--window-size=1280,800"],
                )
                used_chrome = True
        except Exception:
            browser = None
        if browser is None:
            # Chrome 没有/启动失败 → Edge(Windows 自带) → 自带 Chromium, 逐级回退
            for channel in ("msedge", None):
                try:
                    if channel:
                        browser = pw.chromium.launch(
                            headless=False, channel=channel,
                            args=["--window-size=1280,800"],
                        )
                    else:
                        browser = pw.chromium.launch(
                            headless=False,
                            args=["--window-size=1280,800"],
                        )
                    break
                except Exception:
                    browser = None
            if browser is None:
                # 全部失败(显示不可用等) → 降级无头, 避免崩溃
                mode = "headless"
    if browser is None:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]
        )
    # 1280x800 视口 + 新页面自动置顶/聚焦
    page = browser.new_page(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # 反检测: 隐藏 webdriver 标记
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
    """)
    try:
        page.bring_to_front()
    except Exception:
        pass
    _browser_singleton["browser"] = browser
    _browser_singleton["page"] = page
    _browser_singleton["mode"] = mode
    _browser_singleton["chrome"] = used_chrome
    _browser_singleton["pw"] = pw
    return page


def browser(action: str, **kw):
    """
    控制浏览器(Playwright):
      browser('open', url='https://...')          打开网页
      browser('eval', js='document.title')         执行 JS, 返回结果
      browser('click', selector='#btn')            点击元素
      browser('type', selector='#input', text='x') 输入文字
      browser('text')                              提取页面可见文字
      browser('screenshot')                        截图(返回 base64 PNG)
      browser('back') / browser('close')           后退/关闭
    返回统一 dict: {"ok": bool, ...} 或错误。
    """
    action = (action or "").lower()
    try:
        page = _get_page()
    except Exception as e:
        hint = ("python -m playwright install chromium" if os.name == "nt"
                else "sudo python3 -m playwright install-deps chromium")
        return {"ok": False, "error": f"浏览器启动失败: {e}(可能需要: {hint})"}

    try:
        if action == "open":
            url = kw.get("url", "about:blank")
            # 稳健打开: networkidle + 显式等待 + 失败重试
            max_retries = 3
            last_err = None
            for attempt in range(max_retries):
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    # 关键: 等待网络空闲, 确保动态内容加载完
                    page.wait_for_load_state("networkidle", timeout=15000)
                    page.wait_for_timeout(500)
                    mode = _browser_singleton.get("mode", "headless")
                    if mode == "headless":
                        msg = f"已打开网页(无头模式, 桌面无窗口): {url}"
                    elif _browser_singleton.get("chrome"):
                        msg = f"已在桌面打开 Google Chrome 窗口: {url}"
                    else:
                        msg = f"未检测到 Google Chrome，已用 Chromium 打开窗口: {url}"
                    return {"ok": True, "msg": msg, "title": page.title()}
                except Exception as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        page.wait_for_timeout(1500 * (attempt + 1))
                        continue
            return {"ok": False, "error": f"打开网页失败(重试{max_retries}次): {last_err}"}

        if action == "eval":
            js = kw.get("js", "")
            return {"ok": True, "result": page.evaluate(js)}

        if action == "click":
            sel = kw.get("selector", "")
            max_retries = 3
            last_err = None
            for attempt in range(max_retries):
                try:
                    # 显式等待元素可见/可点击
                    page.wait_for_selector(sel, state="visible", timeout=10000)
                    page.click(sel, timeout=5000)
                    page.wait_for_timeout(400)
                    return {"ok": True, "result": f"已点击: {sel}"}
                except Exception as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        page.wait_for_timeout(1000 * (attempt + 1))
                        continue
            return {"ok": False, "error": f"点击失败(重试{max_retries}次): {last_err}"}

        if action == "type":
            sel, text = kw.get("selector", ""), kw.get("text", "")
            max_retries = 3
            last_err = None
            for attempt in range(max_retries):
                try:
                    page.wait_for_selector(sel, state="visible", timeout=10000)
                    page.fill(sel, text, timeout=5000)
                    return {"ok": True, "result": f"已输入: {text}"}
                except Exception as e:
                    last_err = e
                    if attempt < max_retries - 1:
                        page.wait_for_timeout(1000 * (attempt + 1))
                        continue
            return {"ok": False, "error": f"输入失败(重试{max_retries}次): {last_err}"}

        if action == "text":
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    return {"ok": True, "text": (page.inner_text("body") or "")[:4000]}
                except Exception as e:
                    if attempt < max_retries - 1:
                        page.wait_for_timeout(500)
                        continue
                    return {"ok": False, "error": f"获取文本失败: {e}"}

        if action == "wait":
            # 显式等待: wait_for_selector / wait_for_load_state / timeout(ms)
            sel = kw.get("selector")
            state = kw.get("state", "visible")
            timeout = kw.get("timeout", 10000)
            if sel:
                page.wait_for_selector(sel, state=state, timeout=timeout)
            else:
                page.wait_for_load_state("networkidle", timeout=timeout)
            return {"ok": True, "result": f"已等待: {sel or 'networkidle'}"}

        if action == "screenshot":
            data = page.screenshot(type="png")
            import base64
            return {"ok": True, "image_base64": base64.b64encode(data).decode()}

        if action == "back":
            page.go_back()
            return {"ok": True, "result": "已后退"}

        if action == "close":
            try:
                _browser_singleton["browser"].close()
            except Exception:
                pass
            _browser_singleton["browser"] = None
            _browser_singleton["page"] = None
            _browser_singleton["mode"] = "headless"
            _browser_singleton["chrome"] = False
            return {"ok": True, "result": "已关闭浏览器"}

        return {"ok": False, "error": f"未知动作: {action}"}
    except Exception as e:
        return {"ok": False, "error": f"浏览器操作失败: {e}"}