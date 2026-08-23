#!/usr/bin/env python3
"""
批量去除 static/avatars/ 下所有 PNG 立绘的深色背景。
使用 numpy 向量化 + scipy 形态学操作实现高效背景去除。
"""

import os
import sys
import glob
import numpy as np
from PIL import Image, ImageFilter

try:
    from scipy import ndimage
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

AVATAR_DIR = os.path.join(os.path.dirname(__file__), "static", "avatars")


def list_targets():
    files = sorted(glob.glob(os.path.join(AVATAR_DIR, "*.png")))
    targets = []
    for f in files:
        basename = os.path.splitext(os.path.basename(f))[0]
        if basename.endswith("_orig"):
            continue
        if basename in ("user-sprite", "doubao"):
            continue
        targets.append(f)
    return targets


def get_bg_color(arr):
    """从四个角的 5% 区域采样，取中位数作为背景色。"""
    h, w = arr.shape[:2]
    s = max(1, min(w, h) // 20)  # 5% 边长
    corners = [
        arr[:s, :s],
        arr[:s, -s:],
        arr[-s:, :s],
        arr[-s:, -s:],
    ]
    samples = np.concatenate([c.reshape(-1, 3) for c in corners])
    return np.median(samples, axis=0)


def build_alpha_mask(arr, bg_color, tolerance=50):
    """
    计算每个像素与背景色的距离，距离越远越不透明（前景）。
    返回 0-255 的 alpha mask。
    """
    bg = np.array(bg_color, dtype=np.float32)
    diff = np.sqrt(np.sum((arr.astype(np.float32) - bg) ** 2, axis=2))

    # 距离 < tolerance 的部分视为背景（alpha=0）
    # 距离在 tolerance ~ tolerance*3 之间做线性过渡
    # 距离 > tolerance*3 完全前景（alpha=255）
    t1 = tolerance
    t2 = tolerance * 3

    alpha = np.clip((diff - t1) / (t2 - t1), 0, 1) * 255

    # 形态学闭运算填充前景内部的小洞（scipy 可用时）
    if HAS_SCIPY:
        # 将 alpha 二值化后做闭运算，再恢复为软 mask
        binary = (alpha > 128).astype(np.uint8)
        # 闭运算：先膨胀再腐蚀，填充小洞
        structure = np.ones((5, 5))
        binary = ndimage.binary_closing(binary, structure=structure, iterations=3).astype(np.uint8)
        # 再对结果做距离变换，产生平滑的软边缘
        # 用高斯模糊代替
        from scipy.ndimage import gaussian_filter
        alpha = gaussian_filter(binary.astype(np.float32) * 255, sigma=3)
    else:
        # 无 scipy 时，用 PIL 模糊
        mask_img = Image.fromarray(alpha.astype(np.uint8))
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=3))
        alpha = np.array(mask_img)

    return alpha.astype(np.uint8)


def detect_and_blur_watermark(pil_img):
    """检测右下角水印并模糊。"""
    w, h = pil_img.size
    # 取右下角 15% x 8% 区域
    crop_box = (int(w * 0.82), int(h * 0.90), w, h)
    crop = pil_img.crop(crop_box).convert("L")
    pixels = np.array(crop)

    # 水印文字通常比背景亮
    bright_ratio = np.mean(pixels > 200)

    if 0.005 < bright_ratio < 0.08:
        region = pil_img.crop(crop_box)
        blurred = region.filter(ImageFilter.GaussianBlur(radius=8))
        blurred = blurred.filter(ImageFilter.GaussianBlur(radius=8))
        pil_img.paste(blurred, crop_box)
        return True
    return False


def process_image(path):
    basename = os.path.basename(path)
    print(f"  [{basename}] 正在处理...", flush=True)

    try:
        pil_img = Image.open(path)
        arr = np.array(pil_img.convert("RGB"))
    except Exception as e:
        return f"[{basename}] ❌ 打开失败: {e}"

    orig_size = pil_img.size

    # 1) 获取背景色
    bg_color = get_bg_color(arr)
    print(f"    背景色: RGB({bg_color[0]:.0f}, {bg_color[1]:.0f}, {bg_color[2]:.0f})", flush=True)

    # 2) 构建 alpha mask
    alpha = build_alpha_mask(arr, bg_color, tolerance=45)

    # 3) 合成 RGBA
    result = Image.fromarray(arr).convert("RGBA")
    result.putalpha(Image.fromarray(alpha))

    # 4) 水印处理
    has_watermark = detect_and_blur_watermark(result)
    if has_watermark:
        print(f"    检测到水印，已模糊", flush=True)

    # 5) 保存
    result.save(path, "PNG")

    # 统计透明占比
    alpha_arr = np.array(result.getchannel("A"))
    total = alpha_arr.size
    transparent = np.sum(alpha_arr < 10)
    alpha_pct = transparent / max(total, 1) * 100

    return (
        f"[{basename}] ✅ {orig_size[0]}x{orig_size[1]} → {result.size[0]}x{result.size[1]}  "
        f"透明 {alpha_pct:.1f}%  水印{'✓' if has_watermark else ''}"
    )


def main():
    targets = list_targets()
    print(f"找到 {len(targets)} 张待处理图片\n")

    results = []
    for path in targets:
        r = process_image(path)
        results.append(r)

    print(f"\n{'='*60}")
    print("处理结果汇总：")
    print(f"{'='*60}")
    for r in results:
        print(r)
    print(f"\n共处理 {len(results)} 张。")


if __name__ == "__main__":
    main()
