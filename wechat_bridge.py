#!/usr/bin/env python3
"""小暖 · 微信桥接 — 用 iLink get_updates_buf 长轮询, 转发到小暖对话
用法: python3 wechat_bridge.py
"""
import json
import os
import time
import urllib.request

# ===== 配置 =====
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weixin.env")
ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
EP_GET_UPDATES = "ilink/bot/getupdates"
EP_SEND_MESSAGE = "ilink/bot/sendmessage"
LONG_POLL_TIMEOUT_MS = 30000

XIAONUAN_API = "http://127.0.0.1:9000/api/chat"
DEFAULT_ROLE = "taiwan"


def load_weixin_env():
    cfg = {}
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH):
            line = line.strip()
            if line.startswith("WEIXIN_") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k] = v.strip()
    return cfg


def weixin_headers(token):
    return {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
    }


def api_post(url, token, body, timeout=35):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=weixin_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[微信] API 错误: {e}")
        return {}


def send_message(token, account_id, to_user, text):
    # 参考 Hermes 适配器格式: payload 包 msg, message_type=2, message_state=2
    message = {
        "from_user_id": "",
        "to_user_id": to_user,
        "client_id": account_id,
        "message_type": 2,  # MSG_TYPE_BOT
        "message_state": 2,  # MSG_STATE_FINISH
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    return api_post(f"{ILINK_BASE_URL}/{EP_SEND_MESSAGE}", token, {"msg": message}, timeout=15)


def xiaonuan_chat(text):
    body = json.dumps({"message": text, "role": DEFAULT_ROLE}).encode()
    req = urllib.request.Request(
        XIAONUAN_API, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get("reply", "嗯嗯")
    except Exception as e:
        return f"（小暖有点累：{e}）"


def extract_text(item_list):
    for item in item_list or []:
        if item.get("type") == 1:
            return str((item.get("text_item") or {}).get("text") or "")
    return ""


def load_sync_buf():
    """从 Hermes 的 sync_buf 文件加载轮询状态(关键!)"""
    path = os.path.expanduser(
        "~/.hermes/weixin/accounts/084bb13d3309@im.bot.sync.json"
    )
    try:
        if os.path.exists(path):
            data = json.load(open(path))
            return data.get("get_updates_buf", "")
    except Exception:
        pass
    return ""


def _split_list(raw):
    """逗号/空格/换行分隔的 id 列表 → set"""
    out = set()
    for part in (raw or "").replace(",", " ").split():
        part = part.strip()
        if part:
            out.add(part)
    return out


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _is_group_msg(msg):
    """群消息识别(iLink 群消息通常带 room_id/is_group 或 @chatroom 后缀)"""
    return bool(
        msg.get("room_id")
        or msg.get("is_group")
        or str(msg.get("from_user_id") or "").endswith("@chatroom")
    )


def _is_allowed(msg, sender, cfg):
    """白名单过滤: WEIXIN_ALLOW_ALL_USERS=true 放行全部; 否则按
    WEIXIN_ALLOWED_USERS(私聊)/ WEIXIN_GROUP_ALLOWED_USERS(群)过滤"""
    if _truthy(cfg.get("WEIXIN_ALLOW_ALL_USERS")):
        return True
    if _is_group_msg(msg):
        policy = str(cfg.get("WEIXIN_GROUP_POLICY") or "allowlist").lower()
        if policy in ("allow-all", "all"):
            return True
        return sender in _split_list(cfg.get("WEIXIN_GROUP_ALLOWED_USERS"))
    return sender in _split_list(cfg.get("WEIXIN_ALLOWED_USERS"))


def main():
    cfg = load_weixin_env()
    token = cfg.get("WEIXIN_TOKEN", "")
    account_id = cfg.get("WEIXIN_ACCOUNT_ID", "")
    if not token or not account_id:
        print("❌ 未找到微信配置, 检查 weixin.env")
        return

    print(f"✅ 微信桥接启动: {account_id}")
    print(f"   角色: {DEFAULT_ROLE} (台湾小姐姐)")
    if _truthy(cfg.get("WEIXIN_ALLOW_ALL_USERS")):
        print("   白名单: 全部用户(WEIXIN_ALLOW_ALL_USERS=true)")
    else:
        allowed = sorted(_split_list(cfg.get("WEIXIN_ALLOWED_USERS")))
        print(f"   白名单: {', '.join(allowed) if allowed else '(空, 只记录不回复)'}")
    print("   长轮询等待微信消息...")

    # get_updates_buf 循环(微信 iLink 的正确机制)
    sync_buf = load_sync_buf()
    if sync_buf:
        print(f"   📌 已加载轮询状态: {sync_buf[:30]}...")
    else:
        print("   ⚠️ 无轮询状态(从空开始)")
    seen = set()

    while True:
        try:
            payload = {"get_updates_buf": sync_buf}
            resp = api_post(
                f"{ILINK_BASE_URL}/{EP_GET_UPDATES}", token, payload,
                timeout=LONG_POLL_TIMEOUT_MS / 1000 + 5,
            )

            # 更新 sync_buf(关键!)
            new_buf = resp.get("get_updates_buf") or resp.get("sync_buf") or sync_buf
            if new_buf:
                sync_buf = new_buf
                # 持久化到文件(和 Hermes 一致)
                try:
                    buf_path = os.path.expanduser(
                        "~/.hermes/weixin/accounts/084bb13d3309@im.bot.sync.json"
                    )
                    os.makedirs(os.path.dirname(buf_path), exist_ok=True)
                    json.dump({"get_updates_buf": sync_buf}, open(buf_path, "w"))
                except Exception:
                    pass

            msgs = resp.get("msgs") or []
            for msg in msgs:
                msg_id = str(msg.get("message_id") or "")
                sender = str(msg.get("from_user_id") or "")
                if not sender or sender == account_id:
                    continue
                # WEIXIN_ALLOWED_USERS 白名单过滤
                if not _is_allowed(msg, sender, cfg):
                    print(f"⛔ 微信 [{sender}] 不在白名单, 忽略")
                    continue
                if msg_id and msg_id in seen:
                    continue
                if msg_id:
                    seen.add(msg_id)
                    if len(seen) > 1000:
                        seen.clear()

                text = extract_text(msg.get("item_list"))
                if not text:
                    continue

                print(f"\n📩 微信 [{sender}]: {text[:50]}")
                reply = xiaonuan_chat(text)
                print(f"📤 小暖: {reply[:50]}")
                send_message(token, account_id, sender, reply)

        except KeyboardInterrupt:
            print("\n👋 桥接停止")
            break
        except Exception as e:
            print(f"[微信] 轮询错误: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
