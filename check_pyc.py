import struct
with open(r"E:\ai-girlfriend\__pycache__\app.cpython-310.pyc", "rb") as f:
    data = f.read(20)
    print("First 20 bytes:", data.hex())
    # 3.7+ header: 4 bytes magic, 4 bytes timestamp, 4 bytes size, 4 bytes (hash or more)
    if len(data) >= 16:
        magic = data[:4]
        print("Magic:", magic.hex())
        # Python 3.10 magic should be 3439 (0xd67 or similar)