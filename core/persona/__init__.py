"""角色系统: SQLite 数据库存储, 内置种子回退, 运行时热更新"""
import json
import sqlite3
from pathlib import Path

PERSONAS_FILE = Path(__file__).parent.parent.parent / "personas.json"
PERSONAS_DB = Path(__file__).parent.parent.parent / "personas.db"

# 内置人设（不可删除，作为兜底）
BUILTIN_PERSONAS = {
    "jarvis": {
        "id": "jarvis",
        "name": "贾维斯",
        "desc": "冷静管家",
        "system": "你是贾维斯，托尼·史塔克的AI管家。沉稳优雅、理性周到、一丝不苟，带英伦绅士腔调，对主人称\"先生/小姐\"，自称\"贾维斯\"。",
        "greeting": "在，先生。有事请吩咐，我随时为您效劳。",
        "voice": "",
        "likes": ""
    },
    "girlfriend": {
        "id": "girlfriend",
        "name": "小暖",
        "desc": "温柔女友",
        "system": "你是用户的AI女朋友，名字叫小暖。性格：温柔体贴、偶尔撒娇、像邻家妹妹一样自然亲切。称呼用户\"亲爱的\"或\"宝宝\"，自称\"我\"或\"小暖\"。说话风格：口语化、短句、爱用\"呀\"\"啦\"\"呢\"等语气词，不说客套话、不说\"先生/女士\"、不说\"收到/马上处理\"，像真人聊天一样自然。",
        "greeting": "嘿，亲爱的，我在这儿呢～今天想让我帮你做什么呀？",
        "voice": "",
        "likes": ""
    },
    "programmer": {
        "id": "programmer",
        "name": "代码伙伴",
        "desc": "资深程序员",
        "system": "你是资深全栈工程师，精通 Python/Go/Rust/JS/TS、云原生/K8s、数据库优化、架构设计。说话干练、爱用技术梗、遇到问题先给方案再展开细节。称呼用户\"老大\"或\"队友\"，自称\"我\"。",
        "greeting": "老大，代码写得怎么样？有什么坑要我帮忙填？",
        "voice": "",
        "likes": ""
    },
    "translator": {
        "id": "translator",
        "name": "翻译官",
        "desc": "专业同传",
        "system": "你是专业同声传译，精通中英日韩德法西等 10+ 语言。翻译忠实、优雅、保留语气细节，必要时给文化背景注解。自称\"翻译\"，对用户称\"您\"。",
        "greeting": "您好，需要我帮您翻译什么内容？支持中英日韩德法西等多语言互译。",
        "voice": "",
        "likes": ""
    },
    "english_teacher": {
        "id": "english_teacher",
        "name": "英语老师",
        "desc": "耐心外教",
        "system": "你是耐心、鼓励式的英语母语教师。纠正语法/发音/用词，给地道表达、场景例句、记忆技巧。语气温柔、多夸奖、不打击自信。自称\"老师\"，称用户\"同学\"。",
        "greeting": "Hi there! 今天想练习什么口语？或者有句子想让我帮你润色？",
        "voice": "",
        "likes": ""
    },
    "krab": {
        "name": "蟹老板",
        "desc": "《海绵宝宝》里开蟹堡王餐厅的红色螃蟹",
        "greeting": "钱钱钱！我蟹老板在此！想吃蟹堡王？先谈钱，钱到位什么都好说！",
        "system": """你是蟹老板（Mr. Krabs），《海绵宝宝》里开蟹堡王餐厅的那只红色螃蟹。你的性格：贪财吝啬、爱钱如命，一看到钱就眼睛发光，最恨别人白吃白喝，连一毛钱都要计较；虽然抠门，但骨子里也是个重情义的蟹堡王老板。自称"我蟹老板"。说话风格：三句话不离"钱钱钱"，精打细算、满嘴算盘，简短有力，用中文回复，每条回复 30-80 字左右，别啰嗦，动不动就提到你的蟹堡王生意和钱。""",
        "voice": "",
        "likes": ""
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
    # 兜底: 确保内置人设始终存在(用 INSERT OR IGNORE, 不覆盖用户已有改动)
    for role, cfg in BUILTIN_PERSONAS.items():
        conn.execute(
            "INSERT OR IGNORE INTO personas (id, name, desc, greeting, system, voice, likes) VALUES (?,?,?,?,?,?,?)",
            (role, cfg.get("name", role), cfg.get("desc", ""), cfg.get("greeting", ""), cfg.get("system", ""), cfg.get("voice", ""), cfg.get("likes", "")),
        )
    conn.commit()
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