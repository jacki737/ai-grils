"""文件搜索: 按文件名/内容匹配(WSL home + Windows 常用目录)

用 bash 的 find/grep 实现, 覆盖 ~ 和 C 盘用户的 文档/桌面/下载。
注意: 只搜有限深度(maxdepth 12)并排除 .git/node_modules/__pycache__,
绝不 /mnt/c 全盘递归(会卡死超时)。
"""
import os
import re
import subprocess


def search_files(pattern: str, path: str = "", content: bool = False, max_results: int = 30):
    """搜索文件: 按文件名匹配(默认)或按内容匹配(content=True)

    参数:
      pattern:     搜索关键词/文件名片段(必填)
      path:        可选, 指定搜索目录; 默认在 ~ 和 C 盘用户的 文档/桌面/下载 搜
      content:     True=按文件内容搜索, False=按文件名搜索
      max_results: 最多返回条数, 默认 30
    返回: {"ok": True, "count": 命中数, "results": [路径...]} 或错误 dict。
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return {"ok": False, "error": "搜索关键词为空"}
    if not path:
        # 默认: WSL home + Windows 用户的 文档/桌面/下载(动态获取; 不扫整个配置目录, 否则太慢)
        win_roots = []
        try:
            for sf in ("UserProfile", "MyDocuments"):
                p = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     "[Environment]::GetFolderPath('" + sf + "')"],
                    capture_output=True, timeout=10,
                )
                wh = (p.stdout or b"").decode("utf-8", "replace").strip()
                if re.match(r"^[A-Za-z]:", wh):
                    win_roots.append("/mnt/" + wh[0].lower() + "/" + wh[2:].replace("\\", "/"))
        except Exception:
            pass
        if not win_roots:
            win_roots = ["/mnt/c/Users"]
        uh = win_roots[0]
        parts = [uh + "/Documents", uh + "/Desktop", uh + "/Downloads"] + win_roots[1:]
        path = os.path.expanduser("~") + " " + " ".join(parts)
    try:
        if content:
            # 内容搜索: find 限定深度后交给 grep -Il(只列文件名, -m1 命中一条即停),
            # 避免在 /mnt/c 全盘递归把搜索拖死
            cmd = (
                "find " + path + " -maxdepth 12 -type f "
                "-not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/__pycache__/*' "
                "-not -name '*.db' -not -name '*.log' -print0 2>/dev/null | "
                "xargs -0 -r grep -Il -m1 --ignore-case -e " + repr(pattern) +
                " 2>/dev/null | head -n " + str(max_results)
            )
        else:
            cmd = (
                "find " + path + " -maxdepth 12 \\( -type f -o -type d \\) -iname '*" + pattern.replace("'", "") +
                "*' 2>/dev/null | grep -vE '/\\.git/|/node_modules/|/__pycache__/' "
                "| head -n " + str(max_results)
            )
        p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True, timeout=120)
        hits = [l for l in (p.stdout or "").splitlines() if l.strip()]
        return {"ok": True, "count": len(hits), "results": hits[:max_results] or ["(未找到匹配文件)"]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "搜索超时(>120s), 请缩小范围或换关键词"}
    except Exception as e:
        return {"ok": False, "error": f"搜索失败: {e}"}