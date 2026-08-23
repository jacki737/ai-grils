from xdis import disassemble_file

# 直接传 pyc 文件路径
out_file = open(r"E:\ai-girlfriend\app_disasm.txt", "w", encoding="utf-8")
disassemble_file(
    r"E:\ai-girlfriend\__pycache__\app.cpython-310.pyc",
    outstream=out_file,
    show_source=True
)
out_file.close()
print("Disassembly written")

# 读取看看
with open(r"E:\ai-girlfriend\app_disasm.txt", "r", encoding="utf-8") as f:
    lines = f.readlines()
    for line in lines[:300]:
        print(line.rstrip())