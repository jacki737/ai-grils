import sqlite3
from pathlib import Path

conn = sqlite3.connect(str(Path(__file__).with_name("personas.db")))
c = conn.cursor()

c.execute('SELECT id FROM personas WHERE id=?', ('jarvis',))
if c.fetchone():
    print('jarvis already exists')
else:
    c.execute('''INSERT INTO personas (id, name, desc, greeting, system, voice, likes) 
                 VALUES (?,?,?,?,?,?,?)''',
              ('jarvis', '贾维斯', '钢铁侠的AI管家，沉稳优雅、理性周到',
               '您好，先生。贾维斯在此，随时为您效劳。',
               '你是贾维斯，钢铁侠托尼·斯塔克的AI管家。性格沉稳优雅、理性周到、一丝不苟，带着英伦绅士腔调。自称"贾维斯"，对用户称"先生"。说话简洁精准、优雅得体，中文回复，必要时自然夹杂英文短语，每条 30-80 字。',
               'xiaoai:冰糖', ''))
    conn.commit()
    print('jarvis added')

c.execute('SELECT id, name FROM personas')
for r in c.fetchall():
    print(r)
conn.close()