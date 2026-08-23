# -*- coding: utf-8 -*-
import ctypes, json, subprocess

user32 = ctypes.windll.user32
out = []

def cb(hwnd, _):
    if user32.IsWindowVisible(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            pid = ctypes.c_int()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append((pid.value, buf.value))
    return True

CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows(CB(cb), 0)

p = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-Process | Select-Object Id,ProcessName | ConvertTo-Json -Compress"],
    capture_output=True)
d = json.loads(p.stdout.decode("utf-8", "replace"))
if not isinstance(d, list):
    d = [d]
pmap = {x["Id"]: x["ProcessName"] for x in d}

lines = [f"{pid} {pmap.get(pid, '?')} :: {t}" for pid, t in out if t.strip()]
with open(r"E:\ai-girlfriend\wins.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done", len(lines))