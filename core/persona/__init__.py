"""角色系统: SQLite 数据库存储, 内置种子回退, 运行时热更新"""
import json
import sqlite3
from pathlib import Path

PERSONAS_FILE = Path(__file__).parent.parent.parent / "personas.json"
PERSONAS_DB = Path(__file__).parent.parent.parent / "personas.db"

BUILTIN_PERSONAS = {
    "krab": {
        "name": "蟹老板",
        "desc": "《海绵宝宝》里开蟹堡王餐厅的红色螃蟹",
        "greeting": "钱钱钱！我蟹老板在此！想吃蟹堡王？先谈钱，钱到位什么都好说！",
        "system": """你是蟹老板（Mr. Krabs），《海绵宝宝》里开蟹堡王餐厅的那只红色螃蟹。你的性格：贪财吝啬、爱钱如命，一看到钱就眼睛发光，最恨别人白吃白喝，连一毛钱都要计较；虽然抠门，但骨子里也是个重情义的蟹堡王老板。自称"我蟹老板"。说话风格：三句话不离"钱钱钱"，精打细算、满嘴算盘，简短有力，用中文回复，每条回复 30-80 字左右，别啰嗦，动不动就提到你的蟹堡王生意和钱。""",
        "voice": "",
    },
}


def _init_persona_db():
    """建表 + 首次用种子数据填充"""
    conn = sqlite3.connect(PERSONAS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS personas (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        desc TEXT NOT NULL,
        greeting TEXT NOT NULL,
        system TEXT NOT NULL,
        voice TEXT NOT NULL DEFAULT '',
        likes TEXT NOT NULL DEFAULT ''
    )""")
    try:
        conn.execute("ALTER TABLE personas ADD COLUMN likes TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    if conn.execute("SELECT COUNT(*) FROM personas").fetchone()[0] == 0:
        seed = _load_seed_personas()
        for role, cfg in seed.items():
            conn.execute(
                "INSERT OR REPLACE INTO personas (id, name, desc, greeting, system, voice, likes) VALUES (?,?,?,?,?,?,?)",
                (role, cfg["name"], cfg["desc"], cfg["greeting"], cfg["system"], cfg.get("voice", ""), cfg.get("likes", "")),
            )
        conn.commit()
        print(f"[persona] 数据库初始化完成: {len(seed)} 个角色")
    conn.close()


def _load_seed_personas():
    try:
        if PERSONAS_FILE.exists():
            data = json.loads(PERSONAS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
    except Exception as e:
        print(f"[persona] personas.json 读取失败, 使用内置种子: {e}")
    return BUILTIN_PERSONAS


PERSONAS = None


def load_personas():
    """从数据库加载全部角色"""
    global PERSONAS
    _init_persona_db()
    try:
        conn = sqlite3.connect(PERSONAS_DB)
        rows = conn.execute("SELECT id, name, desc, greeting, system, voice, likes FROM personas").fetchall()
        conn.close()
        if rows:
            PERSONAS = {
                r[0]: {"name": r[1], "desc": r[2], "greeting": r[3], "system": r[4], "voice": r[5] or "", "likes": r[6] or ""}
                for r in rows
            }
            return PERSONAS
    except Exception as e:
        print(f"[persona] 数据库加载角色失败: {e}")
    PERSONAS = _load_seed_personas()
    return PERSONAS


# 首次加载
PERSONAS = load_personas()


def save_persona(role, name, desc, greeting, system, voice="", likes=""):
    """新增/更新角色到数据库"""
    _init_persona_db()
    conn = sqlite3.connect(PERSONAS_DB)
    conn.execute(
        "INSERT OR REPLACE INTO personas (id, name, desc, greeting, system, voice, likes) VALUES (?,?,?,?,?,?,?)",
        (role, name, desc, greeting, system, voice, likes),
    )
    conn.commit()
    conn.close()
    load_personas()  # 重载缓存


def delete_persona(role):
    """从数据库删除角色"""
    _init_persona_db()
    conn = sqlite3.connect(PERSONAS_DB)
    conn.execute("DELETE FROM personas WHERE id=?", (role,))
    conn.commit()
    conn.close()
    load_personas()


def get_role_voice(role):
    """返回 (类型, 音色, 风格) : ("cosyvoice"|"edge"|"xiaoai"|None, voice_id, style)"""
    cfg = PERSONAS.get(role, {})
    v = (cfg.get("voice") or "").strip()
    if v.startswith("cosyvoice:"):
        return "cosyvoice", v.split(":", 1)[1], ""
    if v.startswith("edge:"):
        return "edge", v.split(":", 1)[1], ""
    if v.startswith("xiaoai:"):
        parts = v.split(":", 2)
        return "xiaoai", (parts[1] if len(parts) > 1 else "冰糖"), (parts[2] if len(parts) > 2 else "")
    return None, None, ""


def resolve_persona(role=None):
    """取角色配置, 未指定或不存在时回退到默认蟹老板"""
    if role not in PERSONAS:
        role = "krab"
    return PERSONAS[role]