#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JPG + MP4 → 鸿蒙实况照片（HarmonyOS Live Photo / Moving Photo）命令行入口。

这是项目的推荐入口，负责三件事：
  1. 解析命令行参数（批量 / 单组 / 只校验 / 帮助）
  2. 决定每个文件校验结果怎么展示（默认逐条打印，--quiet 收成一行）
  3. 汇总退出码

真正的格式实现（60 字节尾标记、字节拼接、校验项）在 tools/make_live.py 里。

用法:
  python main.py                          批量：转换 input/ 下所有同名 JPG+MP4
  python main.py -v                       批量 + 逐条校验（等价于 --verbose）
  python main.py --quiet                  批量，只在失败时展开校验
  python main.py 图.jpg 视频.mp4           单组，输出到 out/图.jpg
  python main.py 图.jpg 视频.mp4 出.jpg    单组，指定输出路径
  python main.py --check 出.jpg            只校验一个已有的实况照片文件
  python main.py --help                   显示帮助

退出码:
  0  全部成功
  1  有产物校验失败
  2  输入有误 / 找不到文件（未写任何产物）
"""
import os
import sys

# 不生成 __pycache__，保持目录干净（必须在 import 之前设置）
sys.dont_write_bytecode = True

ROOT = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

import make_live as ml  # noqa: E402

IN_DIR = os.path.join(ROOT, "input")
OUT_DIR = os.path.join(ROOT, "out")

USAGE = """\
JPG + MP4 → 鸿蒙实况照片

用法:
  python main.py                          批量：转换 input/ 下所有同名 JPG+MP4
  python main.py -v                       批量 + 逐条打印全部校验项
  python main.py --quiet                  批量，只在失败时展开校验
  python main.py 图.jpg 视频.mp4           单组，输出到 out/图.jpg
  python main.py 图.jpg 视频.mp4 出.jpg    单组，指定输出路径
  python main.py --check 出.jpg            只校验一个已有的实况照片文件
  python main.py --help                   显示本帮助

选项:
  -v, --verbose   逐条打印每一项校验（批量模式默认也是逐条，加 --quiet 才收起来）
  -q, --quiet     批量模式下只在失败时展开校验
  --check FILE    不生成，只按鸿蒙的解析公式校验一个已有文件

退出码:
  0 全部成功   1 有产物校验失败   2 输入有误（未写任何产物）
"""


def check_only(path: str) -> int:
    """只校验一个已有文件：按 GetMovingPhotoDetailedSize 反解，再检查视频区可解析。"""
    if not os.path.isfile(path):
        print(f"[错误] 找不到文件: {path}")
        return 2

    data = open(path, "rb").read()
    print(f"文件: {path}")
    print(f"大小: {len(data):,} 字节\n")

    if len(data) < ml.MIN_STANDARD_SIZE:
        print(f"[FAIL] 文件小于 {ml.MIN_STANDARD_SIZE} 字节，不可能是实况照片")
        return 1

    info = ml.parse_tail(data)
    print(f"末尾 60 字节: {data[-60:]!r}\n")
    print(f"  IsLivePhoto          = {info['is_live']}")
    print(f"  版本标记             = {info['version_tag']!r}")
    print(f"  播放信息             = {info['duration_tag']!r}")
    print(f"  视频信息             = {info['live_tag']!r}")
    print(f"  imageSize            = {info['image_size']:,}")
    print(f"  videoSize            = {info['video_size']:,}")
    print(f"  extraDataSize        = {info['extra_size']:,}")
    print(f"  含 cinemagraph       = {info['has_cinemagraph']}")

    ok = True
    print()
    if not info["is_live"]:
        print("[FAIL] 末尾 20 字节不以 'LIVE_' 开头 —— 鸿蒙只会当普通静态照片")
        ok = False
    else:
        print("[OK]   末尾 20 字节以 'LIVE_' 开头")

    if not (0 < info["image_size"] <= len(data)):
        print(f"[FAIL] 反算出的 imageSize 不合理: {info['image_size']:,}")
        ok = False
    else:
        print(f"[OK]   反算出的 imageSize 合理")

    if not (0 < info["video_size"] <= len(data)):
        print(f"[FAIL] 反算出的 videoSize 不合理: {info['video_size']:,}")
        ok = False
    else:
        print(f"[OK]   反算出的 videoSize 合理")

    # 视频区应当从 imageSize 处开始，且开头是 ftyp
    start = info["image_size"]
    head = data[start:start + 8]
    if head[4:8] == b"ftyp":
        print(f"[OK]   视频区起点 {start:,} 处是 ftyp，可被解析器识别")
    else:
        print(f"[FAIL] 视频区起点 {start:,} 处不是 ftyp（实际 {head!r}）")
        ok = False

    # 图像区应当以 JPEG 的 SOI 开头、且能解码
    if data[:2] != ml.JPG_SOI:
        print("[FAIL] 文件开头不是 JPEG（FF D8）")
        ok = False
    else:
        try:
            from PIL import Image
            import io
            im = Image.open(io.BytesIO(data))
            im.load()
            ex = im.getexif()
            print(f"[OK]   图像区可解码 {im.size} {im.mode}，EXIF 条目 {len(ex)}")
            print(f"       Make={ex.get(0x010F)!r} Model={ex.get(0x0110)!r} "
                  f"DateTime={ex.get(0x0132)!r}")
        except Exception as e:
            print(f"[FAIL] 图像区解码失败: {e}")
            ok = False

    print()
    print("结论：" + ("这是一个格式正确的鸿蒙实况照片。" if ok else "不是有效的鸿蒙实况照片。"))
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]

    verbose = True     # 批量模式默认逐条打印
    if "-q" in args or "--quiet" in args:
        verbose = False
    if "-v" in args or "--verbose" in args:
        verbose = True
    args = [a for a in args if a not in ("-q", "--quiet", "-v", "--verbose")]

    if not args:
        return ml.run_batch(IN_DIR, OUT_DIR, verbose=verbose)

    if args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    if args[0] == "--check":
        if len(args) < 2:
            print("[错误] --check 后面要跟一个文件路径。")
            print(USAGE)
            return 2
        return check_only(args[1])

    if len(args) < 2:
        print("[错误] 参数不足。")
        print(USAGE)
        return 2

    jpg, mp4 = args[0], args[1]
    out = args[2] if len(args) > 2 else os.path.join(OUT_DIR, os.path.basename(jpg))
    return ml.run_one(jpg, mp4, out, verbose=True)


if __name__ == "__main__":
    sys.exit(main())
