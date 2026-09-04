import uvicorn

if __name__ == '__main__':
    # reload=True: 修改 .py 自动生效(html/js从不需要重启); 切换瞬间有1~2秒中断, watchdog可能误报
    uvicorn.run("app:app", host="0.0.0.0", port=9000, log_level="info", reload=True)
