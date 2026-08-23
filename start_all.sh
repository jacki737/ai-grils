#!/bin/bash
cd /home/marka/ai-girlfriend || exit 1
pgrep -f '[u]vicorn app:app' | xargs -r kill -9
pgrep -f '[m]onitor.py' | xargs -r kill -9
sleep 1
setsid nohup python3 -u monitor.py >> monitor.log 2>&1 & disown
setsid nohup python3 -m uvicorn app:app --host 0.0.0.0 --port 9000 </dev/null >> server.log 2>&1 & disown
sleep 10
echo "=== status ==="
pgrep -f '[u]vicorn app:app' >/dev/null && echo SERVER_UP
pgrep -f '[m]onitor.py' >/dev/null && echo MONITOR_UP
curl -s -o /dev/null -w "api:%{http_code}\n" http://127.0.0.1:9000/api/personas
tail -4 monitor.log
