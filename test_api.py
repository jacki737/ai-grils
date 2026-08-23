import urllib.request, json, time, os, subprocess, threading, sys

# 杀旧进程
for name in ['python.exe', 'uvicorn.exe']:
    subprocess.run(['taskkill', '/f', '/im', name], capture_output=True)
time.sleep(2)

# 启动
def run():
    os.chdir(r'E:\ai-girlfriend')
    import uvicorn
    uvicorn.run('app:app', host='0.0.0.0', port=9000, log_level='info')

t = threading.Thread(target=run, daemon=True)
t.start()
time.sleep(5)

# 测试端点
for ep in ['/api/persona?role=jarvis', '/api/history?role=jarvis', '/api/due', '/api/personas']:
    try:
        r = urllib.request.urlopen(f'http://127.0.0.1:9000{ep}', timeout=10)
        data = json.loads(r.read().decode())
        print(f"{ep}: {r.status} keys={list(data.keys())}")
    except Exception as e:
        print(f"{ep} ERROR: {e}")