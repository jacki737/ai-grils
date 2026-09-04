#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原生桌面客户端: tkinter 窗口 + 文字/语音对话
运行: python desktop_chat.py   (需先启动后端 run_server.py)
"""
import base64
import io
import json
import threading
import time
import urllib.request
import wave
from pathlib import Path

import tkinter as tk
from tkinter.scrolledtext import ScrolledText

API = "http://127.0.0.1:9000"
ROLE = "jarvis"


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(Path(__file__).with_name("desktop_chat.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _post(path, body, timeout=60):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat(message):
    """发消息, 兼容同步/异步两种返回, 最终返回回复文本。"""
    d = _post("/api/chat", {"message": message, "role": ROLE})
    if d.get("async") and d.get("task_id"):
        tid = d["task_id"]
        for _ in range(300):
            time.sleep(0.5)
            t = _post("/api/task_status?task_id=" + tid, {}) if False else _get(
                "/api/task_status?task_id=" + tid)
            if t.get("status") in ("done", "error"):
                return t.get("reply", "（出错了）")
        return "（超时了）"
    return d.get("reply", "")


def _get(path):
    with urllib.request.urlopen(API + path, timeout=30) as r:
        return json.loads(r.read())


def tts_play(text):
    """合成并播放语音(失败静默)。"""
    try:
        req = urllib.request.Request(
            API + "/api/tts", data=json.dumps({"text": text, "role": ROLE}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            wav_bytes = r.read()
        import soundcard as sc
        speaker = sc.default_speaker()
        with wave.open(io.BytesIO(wav_bytes)) as w:
            data = w.readframes(w.getnframes())
            sr = w.getframerate()
            ch = w.getnchannels()
        import numpy as np
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            audio = audio.reshape(-1, ch)
        with speaker.player(samplerate=sr) as p:
            p.play(audio)
    except Exception as e:
        print("[tts]", e)


def record_seconds(sec=5):
    """录 sec 秒 16k 单声道, 返回 wav bytes。"""
    import soundcard as sc
    import numpy as np
    mic = sc.default_microphone()
    sr = 16000
    with mic.recorder(samplerate=sr) as rec:
        data = rec.record(numframes=sr * sec)
    audio = (np.clip(data.flatten(), -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.tobytes())
    return buf.getvalue()


def _init_com():
    """soundcard 在非主线程需要手动初始化 COM(否则报 0x800401f0)"""
    try:
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # APARTMENTTHREADED
    except Exception:
        pass


def _pick_mic():
    """挑一个真实麦克风(排除立体声混音等虚拟设备), 并打日志。"""
    import soundcard as sc
    mics = sc.all_microphones(include_loopback=False)
    _log("[mic-list] 可用麦克风: " + "; ".join(m.name or "?" for m in mics))
    for m in mics:
        name = (m.name or "")
        low = name.lower()
        if ("麦克风" in name or "microphone" in low) and "stereo" not in low:
            return m
    return mics[0] if mics else sc.default_microphone()


class App:
    def __init__(self, root):
        self.root = root
        root.title("小暖")
        root.geometry("420x620")
        root.configure(bg="#faf6f0")

        self.log = ScrolledText(root, font=("Microsoft YaHei", 11),
                                bg="#faf6f0", relief="flat", state="disabled",
                                wrap="word", padx=12, pady=10)
        self.log.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        bottom = tk.Frame(root, bg="#faf6f0")
        bottom.pack(fill="x", padx=8, pady=(0, 10))

        self.entry = tk.Entry(bottom, font=("Microsoft YaHei", 12))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self.on_send())

        self.send_btn = tk.Button(bottom, text="发送", font=("Microsoft YaHei", 11),
                                  command=self.on_send, bg="#8b6f47", fg="white",
                                  relief="flat", padx=14)
        self.send_btn.pack(side="left", padx=(6, 0))

        self.mic_btn = tk.Button(bottom, text="🎤 说话", font=("Microsoft YaHei", 11),
                                 command=self.on_mic, bg="#a08464", fg="white",
                                 relief="flat", padx=10)
        self.mic_btn.pack(side="left", padx=(6, 0))

        self.status = tk.Label(root, text="就绪", anchor="w", font=("Microsoft YaHei", 9),
                               bg="#faf6f0", fg="#888")
        self.status.pack(fill="x", padx=10, pady=(0, 6))

        self._recording = False
        self._append("小暖", "在呢～想聊点什么？")

    def _append(self, who, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M')}] {who}：{text}\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, s):
        self.status.config(text=s)

    def on_send(self):
        msg = self.entry.get().strip()
        if not msg:
            return
        self.entry.delete(0, "end")
        self._append("我", msg)
        self._set_status("思考中…")
        threading.Thread(target=self._worker, args=(msg,), daemon=True).start()

    def _worker(self, msg):
        try:
            _log(f"[chat] 发送: {msg!r}")
            reply = chat(msg)
            _log(f"[chat] 回复: {reply!r}")
        except Exception as e:
            reply = f"（出错了：{e}）"
            _log(f"[chat] 异常: {e!r}")
        self.root.after(0, lambda: self._reply_done(reply))

    def _reply_done(self, reply):
        self._append("小暖", reply)
        self._set_status("就绪")
        threading.Thread(target=tts_play, args=(reply,), daemon=True).start()

    def on_mic(self):
        # 点击开始 -> 再点结束(手动控制, 避免录进环境音)
        if not self._recording:
            self._recording = True
            self.mic_btn.config(text="⏹ 结束", bg="#c0564f")
            self._set_status("录音中… 说完点[结束]")
            threading.Thread(target=self._rec_thread, daemon=True).start()
        else:
            self._recording = False

    def _rec_thread(self):
        try:
            _init_com()
            mic = _pick_mic()
            _log(f"[mic] 使用麦克风: {getattr(mic, 'name', '?')}")
            import numpy as np
            sr = 16000
            MAX_SEC = 60  # 超长音频 ASR 会拒绝, 最长录 60 秒
            chunks = []
            n = 0
            with mic.recorder(samplerate=sr) as rec:
                while self._recording and n < sr * MAX_SEC:
                    chunks.append(rec.record(numframes=sr // 10))
                    n += sr // 10
                    if n % sr == 0:
                        sec = n // sr
                        self.root.after(0, lambda s=sec: self._set_status(f"录音中… {s}秒 (说完点[结束], 最长{MAX_SEC}秒)"))
            auto_stopped = n >= sr * MAX_SEC
            audio = np.concatenate(chunks).flatten()
            maxvol = float(np.abs(audio).max())
            _log(f"[mic] 停止, 时长={len(audio)//sr}秒 最大音量={maxvol:.3f} 自动停={auto_stopped}")
            if maxvol < 0.005:
                self.root.after(0, lambda: self._mic_reset("（没听到声音，再试一次）"))
                return
            wav = self._to_wav(audio, sr)
            self.root.after(0, lambda: self._stt(wav))
        except Exception as e:
            _log(f"[mic] 录音异常: {e!r}")
            self.root.after(0, lambda: self._mic_reset(f"（录音失败：{e}）"))

    @staticmethod
    def _to_wav(audio, sr):
        import numpy as np
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()

    def _mic_reset(self, info):
        self._recording = False
        self.mic_btn.config(state="normal", text="🎤 说话", bg="#a08464")
        self._set_status("就绪")
        if info:
            self._append("小暖", info)

    def _stt(self, wav):
        try:
            _log(f"[stt] 发送识别, wav={len(wav)} bytes")
            b64 = base64.b64encode(wav).decode()
            d = _post("/api/stt", {"audio": b64}, timeout=30)
            text = (d.get("text") or "").strip()
            _log(f"[stt] 识别结果: {text!r}")
        except Exception as e:
            text = f"（识别失败：{e}）"
            _log(f"[stt] 异常: {e!r}")
        if not text or text.startswith("（"):
            self.root.after(0, lambda: self._mic_reset(text or "（没听清）"))
            return
        self._recording = False
        self.mic_btn.config(state="normal", text="🎤 说话", bg="#a08464")
        self._append("我(语音)", text)
        self._set_status("思考中…")
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _mic_got(self, text):
        self._append("我(语音)", text)
        self.mic_btn.config(state="normal", text="🎤 说话")
        self._set_status("思考中…")
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _mic_done(self, _, info):
        self._append("小暖", info)
        self.mic_btn.config(state="normal", text="🎤 说话")
        self._set_status("就绪")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
