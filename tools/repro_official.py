#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格式自证：用 OpenHarmony 的 MergeFile / WriteExtraData 规则，把官方华为实况照片样本
（ref/HUAWEI.jpeg）拆成「图片 + 视频 + cinemagraph + 60 字节尾标记」再拼回去，
要求与官方文件逐字节完全一致。用来证明本项目的格式理解没有偏差。

官方样本分解（由 GetMovingPhotoDetailedSize 公式反算）：
  total        17675998
  liveSize       9832420  <- atoi("LIVE_9832420")
  imageSize    = 17675998 - 9832420 - 40 = 7843538   -> ref/HUAWEI_extracted_image.jpg
  extraDataSize= 60 + 0x00004eab(20139) = 20199      -> 版本标记 "v3_f31_c" 含 _c
  videoSize    = 17675998 - 7843538 - 20199 = 9812261
  布局: image + video + cinemagraph + tail(60)

用法：python tools/repro_official.py     # 一致则退出码 0
"""
import hashlib
import os
import sys

# 导入同目录的 make_live 时不要生成 __pycache__，保持目录干净
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_live import _pad20, MIN_STANDARD_SIZE, parse_tail  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "ref")


def main() -> int:
    full = open(os.path.join(REF, "HUAWEI.jpeg"), "rb").read()
    img = open(os.path.join(REF, "HUAWEI_extracted_image.jpg"), "rb").read()
    vid = open(os.path.join(REF, "HUAWEI_extracted_video.mp4"), "rb").read()

    print("== 官方样本原始信息 ==")
    print("total =", len(full), " image =", len(img), " extracted_video =", len(vid))
    info = parse_tail(full)
    for k, v in info.items():
        print(f"  {k} = {v!r}")

    video_only = full[info["image_size"]:info["image_size"] + info["video_size"]]
    cinema = full[info["image_size"] + info["video_size"]:len(full) - MIN_STANDARD_SIZE]
    print(f"\n切分: video_only={len(video_only)}  cinemagraph={len(cinema)}  "
          f"cinemagraph前8字节={cinema[:8]!r}  末8字节={cinema[-8:]!r}")

    # 按源码规则重建尾标记
    ver = _pad20("v3_f31_c")
    dur = _pad20("0:1299")
    live = _pad20("LIVE_" + str(len(video_only) + 20 + len(cinema)))
    tail = ver + dur + live
    print("\n重建尾标记:")
    print("  ver =", ver)
    print("  dur =", dur)
    print("  live=", live)

    rebuilt = img + video_only + cinema + tail
    same = rebuilt == full
    print("\n== 逐字节比对 ==")
    print("  rebuilt 长度 =", len(rebuilt), " 官方长度 =", len(full))
    print("  长度相等:", len(rebuilt) == len(full))
    print("  内容完全一致:", same)
    print("  rebuilt sha256 =", hashlib.sha256(rebuilt).hexdigest())
    print("  官方   sha256 =", hashlib.sha256(full).hexdigest())

    # 顺带确认：extracted_video.mp4 == video_only + cinemagraph + tail
    vid_ok = vid == video_only + cinema + tail
    print("\n  extracted_video == video_only + cinemagraph + tail:", vid_ok)

    print()
    print("结论：" + ("格式理解与官方样本逐字节一致。" if same else "不一致，格式理解有偏差！"))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
