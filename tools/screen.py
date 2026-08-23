"""Windows 桌面截屏: 物理像素抓取 + 缩放到宽<=1280 转 JPEG base64 供视觉模型

流程: 调 PowerShell(System.Drawing)截全屏 → 存 Windows 临时目录 PNG → PIL 缩放/压缩
→ 转 JPEG base64 返回。截图是 GUI 闭环(gui.py)的眼睛。

跨平台说明:
  - 原生 Windows 运行(python.exe): Windows 路径 C:\\... 直接可读, win_path == wsl_path;
  - WSL 内运行(python3): 需把盘符映射成 /mnt/<盘>/ 路径, 返回 (win, wsl) 两个路径。
"""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import uuid


def _win_temp_paths(fname: str):
    """返回 (Windows临时路径, WSL可读路径), 动态获取 Windows 临时目录, 换机器/换用户也能用

    原生 Windows 上两者相同(Windows 路径本身就是可读的);
    WSL 上返回 (C:\\...\\fname, /mnt/c/.../fname), 供 Windows 侧 PowerShell 写、
    WSL 侧 Python 读同一份文件。
    """
    # 原生 Windows: 直接用系统临时目录, 无需任何 /mnt 转换
    if os.name == "nt":
        p = os.path.join(tempfile.gettempdir(), fname)
        return p, p
    # WSL 分支: 查 Windows 真实临时目录, 再映射成 /mnt/<盘>/
    win_dir = ""
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "[System.IO.Path]::GetTempPath()"],
            capture_output=True, timeout=10,
        )
        win_dir = (p.stdout or b"").decode("utf-8", "replace").strip()
    except Exception:
        pass
    if not re.match(r"^[A-Za-z]:\\", win_dir):
        win_dir = os.environ.get("TEMP") or os.environ.get("TMP") or r"C:\Users\marka\AppData\Local\Temp"
    if not win_dir.endswith("\\"):
        win_dir += "\\"
    drive = win_dir[0].lower()
    wsl_dir = re.sub(r"/+", "/", "/mnt/" + drive + "/" + win_dir[2:].replace("\\", "/"))
    return win_dir + fname, wsl_dir + fname


def screenshot(save_to: str = ""):
    """截取 Windows 桌面屏幕, 返回 base64 JPEG(已缩放到最宽 1280, 供视觉模型分析)

    参数:
      save_to: 可选, 把原始 PNG 另存一份到本地路径(便于排查)。
    返回:
      {"ok": True, "image_base64": JPEG的base64, ...} 或 {"ok": False, "error": ...}
    注意返回的 base64 是 JPEG, 交给视觉模型时要用 data:image/jpeg;base64 前缀。
    """
    try:
        # Windows 临时目录(WSL 可读): 用唯一文件名避免并发冲突
        fname = "shot_" + uuid.uuid4().hex[:8] + ".png"
        win_path, wsl_path = _win_temp_paths(fname)
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
            "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height;"
            "$g = [System.Drawing.Graphics]::FromImage($bmp);"
            "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size);"
            "$bmp.Save('" + win_path + "');"
        )
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, timeout=30,
        )
        if not os.path.exists(wsl_path):
            return {"ok": False, "error": "截图失败: " + (p.stderr or b"").decode("utf-8", "ignore")[:300]}
        # 可选另存原图
        saved_to = ""
        if save_to:
            try:
                sp = os.path.abspath(os.path.expanduser(save_to))
                if os.path.dirname(sp):
                    os.makedirs(os.path.dirname(sp), exist_ok=True)
                shutil.copy(wsl_path, sp)
                saved_to = sp
            except Exception as e:
                return {"ok": False,
                        "error": f"截图成功但保存到 {save_to} 失败: {e}"}
        # 用 PIL 缩放 + 转 JPEG 压缩体积, 控制 base64 大小
        from PIL import Image
        img = Image.open(wsl_path).convert("RGB")
        w, h = img.size
        if w > 1280:
            img = img.resize((1280, int(h * 1280 / w)))
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        try:
            os.remove(wsl_path)
        except Exception:
            pass
        return {
            "ok": True,
            "image_base64": base64.b64encode(buf.getvalue()).decode(),
            "saved_to": saved_to,
            "hint": "image_base64 为 JPEG(base64), 交给视觉模型时用 data:image/jpeg;base64 前缀",
        }
    except Exception as e:
        return {"ok": False, "error": f"截图失败: {e}"}