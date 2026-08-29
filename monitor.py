#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI女友 服务日志监控: 发现异常写 monitor.log (去重/聚合), 每5秒扫描一次."""
import os
import re
import time
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "logs", "app.log")
OUT = os.path.join(BASE, "monitor.log")
PORT = 9000


def stamp():
    return datetime.now().strftime("%m-%d %H:%M:%S")


def log(msg):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (stamp(), msg))


def alive():
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/api/personas" % PORT, timeout=5)
        return True
    except Exception:
        return False


last_report = {}      # 异常类型 -> 上次上报时间
last_alive_check = 0
was_alive = True
size = 0
if os.path.exists(LOG):
    size = os.path.getsize(LOG)

# 聚合状态
stt_empty_count = 0
stt_bad_count = 0
stt_empty_first = 0
stt_bad_first = 0


def report(key, msg, dedup_secs=30):
    now = time.time()
    if key in last_report and now - last_report[key] < dedup_secs:
        return
    last_report[key] = now
    log(msg)


def analyze_line(line):
    global stt_empty_count, stt_bad_count, stt_empty_first, stt_bad_first
    now = time.time()
    if "[STT]" in line and ("ASR:" in line or "whisper:" in line):
        m = re.search(r"(?:ASR|whisper): (.*?) \(([\d.]+)s\)", line)
        txt = m.group(1) if m else line.split(": ")[-1].strip()
        dur = float(m.group(2)) if m and m.group(2) else 0
        if dur > 10:
            report("stt_slow", "STT 太慢: %r (%ss)" % (txt, dur))
        if not txt.strip():
            stt_empty_count += 1
            if not stt_empty_first:
                stt_empty_first = now
            if stt_empty_count >= 3 and now - stt_empty_first <= 120:
                report("stt_empty", "STT 连续 %d 次识别为空(麦克风/音量问题?)" % stt_empty_count)
        else:
            if stt_empty_count:
                stt_empty_count = 0
                stt_empty_first = 0
            if (len(txt) < 2 or not re.search(r"[\u4e00-\u9fff]", txt)) and "同学" not in txt:
                stt_bad_count += 1
                if not stt_bad_first:
                    stt_bad_first = now
                if stt_bad_count >= 3 and now - stt_bad_first <= 120:
                    report("stt_bad", "STT 连续 %d 次异常文本(噪音?): %r" % (stt_bad_count, txt))
            else:
                stt_bad_count = 0
                stt_bad_first = 0
        return

    low = line.lower()
    if "traceback" in low or "critical" in low or "exception" in low or "error" in low:
        report("server_err", "服务异常: %s" % line.strip(), 10)
        return
    if "edge tts 多次重试" in low:
        report("tts_edge_fail", "Edge TTS 重试失败, 走 CosyVoice 兜底", 30)
        return
    if "tts 全部失败" in low:
        report("tts_all_fail", "TTS 全部失败(Edge+CosyVoice)!", 10)
        return
    if "cosyvoice 合成异常" in low or "cosyvoice 兜底失败" in low:
        report("tts_cosy_fail", line.strip(), 30)
        return
    if "/api/chat" in line and " 200 " not in line:
        report("chat_fail", "chat 请求非200: %s" % line.strip(), 10)
        return
    if "/api/stt" in line and " 200 " not in line:
        report("stt_http_fail", "stt 请求非200: %s" % line.strip(), 10)
        return
    if "/api/tts" in line and " 200 " not in line:
        report("tts_http_fail", "tts 请求非200: %s" % line.strip(), 10)
        return


log("=== 监控启动 ===")
while True:
    # 1) 服务存活检查(每30s)
    now = time.time()
    if now - last_alive_check >= 30:
        last_alive_check = now
        up = alive()
        if not up and was_alive:
            report("server_down", "服务不在线! 端口 %d 无响应" % PORT, 0)
        elif up and not was_alive:
            report("server_up", "服务已恢复上线", 0)
        was_alive = up

    # 2) 读取新增日志
    new = ""
    try:
        if not os.path.exists(LOG):
            size = 0
        else:
            ns = os.path.getsize(LOG)
            if ns >= size:
                with open(LOG, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(size)
                    new = f.read()
                size = ns
            else:
                log("日志被截断/轮转, 从尾部重新跟踪")
                with open(LOG, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(0, 2)
                    size = f.tell()
    except Exception:
        pass

    for line in new.splitlines():
        analyze_line(line)

    time.sleep(5)
