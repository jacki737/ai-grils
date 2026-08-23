from core.speak_filter import speak_filter

tests = [
    r"你好 C:\Users\test\file.txt 世界",
    "代码:\n```python\nprint(123)\n```\n结束",
    "JSON: " + '{"key": "value", "long": "x" * 100}' + " 结束",
    "Base64: " + "A" * 150 + " 结束",
    r"路径: /home/user/project/src/main.py 结束",
]

for t in tests:
    print("原:", t[:60])
    print("过滤:", speak_filter(t)[:60])
    print("---")