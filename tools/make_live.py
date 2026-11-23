#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 JPG + MP4 合成为华为/鸿蒙 (HarmonyOS) 实况照片 (Live Photo / Moving Photo)。

格式依据（OpenHarmony 官方源码，非猜测）：
  frameworks/innerkitsimpl/media_library_helper/include/moving_photo_file_utils.h
    LIVE_TAG = "LIVE_"
    LIVE_TAG_LEN = 20, PLAY_INFO_LEN = 20, VERSION_TAG_LEN = 20
    MIN_STANDARD_SIZE = LIVE_TAG_LEN + PLAY_INFO_LEN + VERSION_TAG_LEN = 60

  frameworks/innerkitsimpl/media_library_helper/src/moving_photo_file_utils.cpp
    MergeFile()   = 图片全部字节 + 视频全部字节 + WriteExtraData()
    WriteExtraData() 依次写 3 段，每段定长 20 字节、不足用空格补齐：
      1) GetVersionPositionTag()  -> "v3_f<frame>"    （非相机拍摄；相机拍摄为 "v6_f"）
      2) GetDurationTag()         -> "0:<frame>"      （frame = coverPosition/1000，<600 时用 0: 前缀）
      3) GetVideoInfoTag()        -> "LIVE_<视频字节数 + 20>"

    IsLivePhoto(path): 读文件最后 20 字节，以 "LIVE_" 开头即判定为实况照片。
    GetMovingPhotoDetailedSize():
      liveSize    = atoi(末尾 20 字节去掉 "LIVE_")
      imageSize   = totalSize - liveSize - LIVE_TAG_LEN - PLAY_INFO_LEN
      extraDataSize = 60（版本标记是标准 vN_fM 且不含 _c 时）
      videoSize   = totalSize - imageSize - extraDataSize

  → 所以单文件实况照片 = JPEG + MP4 + 60 字节尾标记。少了这 60 字节，
    鸿蒙媒体库 IsLivePhoto() 返回 false，只当作普通静态 JPEG 显示（这就是"没有实况标志"的原因）。

图像与视频都只做「字节搬运」：像素、EXIF（拍摄参数/时间/GPS/机型）零改动、零重编码。
"""
import hashlib
import os
import struct
import sys

JPG_SOI = b"\xff\xd8"
JPG_EOI = b"\xff\xd9"

# ---- 鸿蒙实况照片尾标记常量（与 OpenHarmony 源码一致）----
LIVE_TAG = "LIVE_"
LIVE_TAG_LEN = 20
PLAY_INFO_LEN = 20
VERSION_TAG_LEN = 20
MIN_STANDARD_SIZE = LIVE_TAG_LEN + PLAY_INFO_LEN + VERSION_TAG_LEN  # 60


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jpeg_segments(data: bytes):
    """遍历 JPEG 段，返回 [(marker, offset, payload_len, header_bytes)]。"""
    if data[:2] != JPG_SOI:
        raise ValueError("不是 JPEG（缺少 SOI）")
    out = []
    i = 2
    while i < len(data) - 1:
        if data[i] != 0xFF:
            out.append(("GARBAGE", i, len(data) - i, data[i:i + 16]))
            break
        m = data[i + 1]
        if m == 0xDA:  # SOS，其后为熵编码数据
            out.append(("SOS", i, len(data) - i, data[i + 4:i + 16]))
            break
        if m == 0xD9:
            out.append(("EOI", i, 2, b""))
            break
        length = int.from_bytes(data[i + 2:i + 4], "big")
        out.append((f"0x{m:02X}", i, length, data[i + 4:i + 16]))
        i += 2 + length
    return out


def find_last_eoi(data: bytes) -> int:
    return data.rfind(JPG_EOI)


def mp4_ftyp_candidates(data: bytes):
    """按 MotionSwap Mp4BoxScanner.findVideoRegion 的判据找 ftyp：
    前 4 字节为 box size 且 16 <= size <= 1024，box 内含 'mp4' 品牌。"""
    cands = []
    start = 0
    while True:
        i = data.find(b"ftyp", start)
        if i < 0:
            break
        if i >= 4:
            size = struct.unpack(">I", data[i - 4:i])[0]
            if 16 <= size <= 1024 and i - 4 + size <= len(data):
                box = data[i - 4:i - 4 + size]
                if b"mp4" in box:
                    cands.append(i - 4)
        start = i + 1
    return cands


def _pad20(s: str) -> bytes:
    """按 OpenHarmony 的写法：不足 20 字节用空格补齐。"""
    b = s.encode("ascii")
    if len(b) > 20:
        raise ValueError(f"尾标记字段超过 20 字节: {s!r}")
    return b + b" " * (20 - len(b))


def build_tail(video_size: int, frame_index: int = 0, cover_position_ms: int = 0,
               camera_shot: bool = False) -> bytes:
    """构造 60 字节尾标记，字段与顺序完全对齐 WriteExtraData()。"""
    ver = ("v6_f" if camera_shot else "v3_f") + str(frame_index)
    frame = cover_position_ms // 1000
    if frame < 600:
        dur = "0:" + str(frame)
    else:
        dur = f"{frame - 600}:{frame}"
    # 与源码一致：LIVE_ 后面是「视频字节数 + 20（版本标记长度）」
    live = LIVE_TAG + str(video_size + VERSION_TAG_LEN)
    tail = _pad20(ver) + _pad20(dur) + _pad20(live)
    assert len(tail) == MIN_STANDARD_SIZE, len(tail)
    return tail


def parse_tail(data: bytes) -> dict:
    """用 OpenHarmony GetMovingPhotoDetailedSize() 的公式反解三段边界。"""
    if len(data) < MIN_STANDARD_SIZE:
        raise ValueError("文件太小，不可能是实况照片")
    ver = data[-MIN_STANDARD_SIZE:-MIN_STANDARD_SIZE + VERSION_TAG_LEN]
    dur = data[-LIVE_TAG_LEN - PLAY_INFO_LEN:-LIVE_TAG_LEN]
    live = data[-LIVE_TAG_LEN:]
    live_s = live.decode("ascii", "replace")
    is_live = live_s.startswith(LIVE_TAG)
    total = len(data)
    live_size = int(live_s[len(LIVE_TAG):].strip() or 0) if is_live else 0
    image_size = total - live_size - LIVE_TAG_LEN - PLAY_INFO_LEN
    # 版本标记是否是标准 vN_fM（决定 extraDataSize 是 60 还是 40）
    import re
    ver_s = ver.decode("ascii", "replace")
    std_ver = re.match(r"^[vV](\d+)_[fF](\d+)", ver_s) is not None
    trimmed = ver_s.split(" ")[0]
    has_cinema = std_ver and (trimmed.endswith("_c") or trimmed.endswith("_C"))
    cinema_size = 0
    if not std_ver:
        extra = LIVE_TAG_LEN + PLAY_INFO_LEN  # 40
    elif not has_cinema:
        extra = MIN_STANDARD_SIZE  # 60
    else:
        # 源码：读 -(60+4) 处 4 字节，逐字节以十六进制无补零拼接（0x00->"0", 0x4e->"4e"）
        hexf = data[-MIN_STANDARD_SIZE - 4:-MIN_STANDARD_SIZE]
        try:
            cinema_size = int("".join(format(b, "x") for b in hexf), 16)
        except Exception:
            cinema_size = 0
        extra = MIN_STANDARD_SIZE + cinema_size
    video_size = total - image_size - extra
    return {
        "is_live": is_live, "version_tag": ver, "duration_tag": dur, "live_tag": live,
        "live_size": live_size, "image_size": image_size,
        "video_size": video_size, "extra_size": extra,
        "has_cinemagraph": has_cinema, "cinemagraph_size": cinema_size,
    }


def build(jpg_path: str, mp4_path: str, out_path: str, **tail_kw) -> dict:
    jpg = open(jpg_path, "rb").read()
    mp4 = open(mp4_path, "rb").read()

    if jpg[:2] != JPG_SOI:
        raise ValueError(f"{jpg_path} 不是 JPEG（开头应为 FF D8）")
    if mp4[4:8] != b"ftyp":
        raise ValueError(f"{mp4_path} 开头不是 MP4（第 4-8 字节应为 ftyp），"
                         f"无法被实况照片解析器识别")

    segs = jpeg_segments(jpg)
    eoi = find_last_eoi(jpg)
    trailer = jpg[eoi + 2:]
    tail = build_tail(len(mp4), **tail_kw)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(jpg)
        f.write(mp4)
        f.write(tail)

    return {"jpg": jpg, "mp4": mp4, "tail": tail, "segs": segs, "eoi": eoi, "trailer": trailer}


class VerifyResult:
    """一次校验的完整结果：按小节收集每条检查，供不同模式决定怎么展示。"""

    def __init__(self):
        self.sections = []      # [(小节标题, [(条目名, 是否通过, 详情, [附加信息行])])]

    def section(self, title):
        items = []
        self.sections.append((title, items))
        return items

    @property
    def ok(self):
        return all(cond for _, items in self.sections for _, cond, _, _ in items)

    @property
    def total(self):
        return sum(len(items) for _, items in self.sections)

    @property
    def failures(self):
        return [(name, detail) for _, items in self.sections
                for name, cond, detail, _ in items if not cond]


def verify(jpg_path: str, mp4_path: str, out_path: str) -> VerifyResult:
    """跑全部校验，返回结构化结果（不打印）。"""
    jpg = open(jpg_path, "rb").read()
    mp4 = open(mp4_path, "rb").read()
    out = open(out_path, "rb").read()
    r = VerifyResult()

    def add(items, name, cond, detail="", extra=None):
        items.append((name, bool(cond), detail, extra or []))

    items = r.section("1. 容器结构")
    add(items, "输出长度 = JPG + MP4 + 60",
        len(out) == len(jpg) + len(mp4) + MIN_STANDARD_SIZE,
        f"{len(out)} == {len(jpg)} + {len(mp4)} + {MIN_STANDARD_SIZE}")
    add(items, "JPG 部分字节完全一致", out[:len(jpg)] == jpg)
    add(items, "MP4 部分字节完全一致", out[len(jpg):len(jpg) + len(mp4)] == mp4)
    add(items, "图像 sha256 保持", sha256(out[:len(jpg)]) == sha256(jpg), sha256(jpg))
    add(items, "视频 sha256 保持", sha256(out[len(jpg):len(jpg) + len(mp4)]) == sha256(mp4), sha256(mp4))

    items = r.section("2. 鸿蒙实况照片判定（IsLivePhoto：末尾 20 字节以 LIVE_ 开头）")
    tail = out[-MIN_STANDARD_SIZE:]
    add(items, "末尾 20 字节以 'LIVE_' 开头", out[-LIVE_TAG_LEN:].startswith(LIVE_TAG.encode()),
        repr(out[-LIVE_TAG_LEN:]))
    add(items, "尾标记共 60 字节", len(tail) == 60, "", [
        f"版本标记 = {tail[0:20]!r}",
        f"播放信息 = {tail[20:40]!r}",
        f"视频信息 = {tail[40:60]!r}",
    ])

    items = r.section("3. 鸿蒙解析公式反算图/视频边界（GetMovingPhotoDetailedSize）")
    info = parse_tail(out)
    add(items, "IsLivePhoto 判定为真", info["is_live"])
    add(items, "反算 imageSize == 原 JPG 大小", info["image_size"] == len(jpg),
        f"{info['image_size']} == {len(jpg)}")
    add(items, "反算 videoSize == 原 MP4 大小", info["video_size"] == len(mp4),
        f"{info['video_size']} == {len(mp4)}")
    add(items, "extraDataSize == 60", info["extra_size"] == 60, str(info["extra_size"]))
    add(items, "视频区起始 == JPG 长度", info["image_size"] == len(jpg))

    items = r.section("4. 华为解析器判据（ftyp 扫描）")
    cands = mp4_ftyp_candidates(out)
    add(items, "恰好找到一个视频起始 ftyp", len(cands) == 1, f"候选偏移 {cands}")
    add(items, "视频起始偏移 == JPG 长度", cands and cands[0] == len(jpg),
        f"{cands[0] if cands else None}")

    items = r.section("5. 图像元数据完整性")
    segs_in = jpeg_segments(jpg)
    segs_out = jpeg_segments(out)
    add(items, "JPEG 段序列不变", [s[0] for s in segs_in] == [s[0] for s in segs_out],
        " / ".join(s[0] for s in segs_out))
    exif_len = int.from_bytes(jpg[4:6], "big")  # APP1 段长度字段（含自身 2 字节）
    exif_in = jpg[2:4 + exif_len]
    add(items, "EXIF APP1 段字节一致（拍摄参数/时间/GPS/机型全保留）",
        out[2:4 + exif_len] == exif_in, f"{len(exif_in)} 字节 @ 偏移 2")
    eoi = find_last_eoi(jpg)
    add(items, "EOI 之后的 ctrace 调试块保留",
        out[eoi:eoi + 2] == JPG_EOI and out[eoi + 2:len(jpg)] == jpg[eoi + 2:])

    items = r.section("6. 可解码性（不改动即应可解码）")
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(out))
        im.load()
        ex = im.getexif()
        sub = ex.get_ifd(0x8769)
        gps = ex.get_ifd(0x8825)
        add(items, "PIL 完整解码", True, f"{im.size} {im.mode}；EXIF 条目 {len(ex)}", [
            f"Make={ex.get(0x010F)!r} Model={ex.get(0x0110)!r} DateTime={ex.get(0x0132)!r}",
            f"DateTimeOriginal={sub.get(0x9003)!r} FNumber={sub.get(0x829D)!r} ISO={sub.get(0x8827)!r}",
            f"GPS 条目 {len(gps)}（源文件本身为未定位占位值，原样保留）",
        ])
    except Exception as e:
        add(items, "PIL 完整解码", False, f"解码失败: {e}")

    return r


def render_verify(r: VerifyResult, verbose: bool = True, indent: str = "") -> None:
    """打印校验结果。

    verbose=True  逐条打印每一节、每一条检查（单组模式的默认行为）
    verbose=False 只打印失败的检查；全通过时压成一行摘要（批量模式用）
    """
    if not verbose and r.ok:
        print(f"{indent}校验 {r.total} 项全部通过")
        return

    for title, items in r.sections:
        if not verbose and all(cond for _, cond, _, _ in items):
            continue  # 静默跳过全通过的小节
        print(f"{indent}== {title} ==")
        for name, cond, detail, extra in items:
            if not verbose and cond:
                continue
            line = ("  [OK]   " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else "")
            print(indent + line)
            if verbose:
                for e in extra:
                    print(indent + "         " + e)

    print()
    if r.ok:
        print(indent + "结论：全部校验通过，产物可用于鸿蒙实况照片。")
    else:
        print(indent + f"结论：{len(r.failures)} 项校验失败，请勿使用产物：")
        for name, detail in r.failures:
            print(indent + f"  - {name}" + (f"（{detail}）" if detail else ""))


def find_pairs(in_dir: str):
    """扫描目录，把同基名的 .jpg/.jpeg 与 .mp4 配成一组。

    返回 (pairs, orphans)：
      pairs    = [(jpg_path, mp4_path), ...]，按文件名排序
      orphans  = [(path, 原因), ...]，有图无视频 / 有视频无图
    """
    if not os.path.isdir(in_dir):
        return [], []

    images, videos = {}, {}
    for name in os.listdir(in_dir):
        p = os.path.join(in_dir, name)
        if not os.path.isfile(p):
            continue
        stem, ext = os.path.splitext(name)
        ext = ext.lower()
        if ext in (".jpg", ".jpeg"):
            images.setdefault(stem, []).append(p)
        elif ext == ".mp4":
            videos.setdefault(stem, []).append(p)

    pairs, orphans = [], []
    for stem in sorted(set(images) | set(videos)):
        imgs = sorted(images.get(stem, []))
        vids = sorted(videos.get(stem, []))
        if len(imgs) > 1:
            # 同基名既有 .jpg 又有 .jpeg 时只取第一个，并提示
            for extra in imgs[1:]:
                orphans.append((extra, f"与 {os.path.basename(imgs[0])} 同名，已忽略"))
        if imgs and vids:
            if len(vids) > 1:
                for extra in vids[1:]:
                    orphans.append((extra, f"与 {os.path.basename(vids[0])} 同名，已忽略"))
            pairs.append((imgs[0], vids[0]))
        elif imgs:
            orphans.append((imgs[0], "缺少同名 .mp4 视频"))
        else:
            orphans.append((vids[0], "缺少同名 .jpg 图片"))
    return pairs, orphans


def run_one(jpg: str, mp4: str, out: str, verbose: bool = True,
            indent: str = "", quiet: bool = False) -> int:
    """处理一组文件，返回退出码：0 成功 / 1 校验失败 / 2 输入有误。

    verbose=True 逐条打印校验项；quiet=True 则连产物路径都不打印。
    """
    if not quiet:
        print(f"{indent}输入图片: {jpg}")
        print(f"{indent}输入视频: {mp4}")
        print(f"{indent}输出实况: {out}")

    for name, p in (("图片", jpg), ("视频", mp4)):
        if not os.path.isfile(p):
            print(f"{indent}[错误] 找不到{name}文件: {p}")
            return 2

    try:
        build(jpg, mp4, out)
    except ValueError as e:
        print(f"{indent}[错误] 输入格式不对: {e}")
        return 2
    except OSError as e:
        print(f"{indent}[错误] 读写失败: {e}")
        return 2

    if not quiet:
        print(f"{indent}已写入 {out}（{os.path.getsize(out):,} 字节）\n")

    r = verify(jpg, mp4, out)
    render_verify(r, verbose=verbose, indent=indent)
    return 0 if r.ok else 1


def run_batch(in_dir: str, out_dir: str, verbose: bool = False) -> int:
    """批量模式：把 in_dir 里所有同名 JPG+MP4 组合都转成实况照片。

    verbose=True 每组都逐条打印全部校验项；默认只在失败时展开。
    """
    pairs, orphans = find_pairs(in_dir)

    if not pairs:
        print(f"[错误] {in_dir} 里没有找到任何「同名 .jpg + .mp4」组合。")
        if orphans:
            print("       发现以下文件但无法配对：")
            for p, why in orphans:
                print(f"         {os.path.basename(p):<40} {why}")
        return 2

    print(f"在 {in_dir} 找到 {len(pairs)} 组待转换素材"
          f"（逐条校验：{'开' if verbose else '关'}）\n")
    results = []
    for i, (jpg, mp4) in enumerate(pairs, 1):
        stem = os.path.splitext(os.path.basename(jpg))[0]
        out = os.path.join(out_dir, stem + ".jpg")
        stale = os.path.exists(out)  # 本轮之前是否已存在同名产物
        print(f"[{i}/{len(pairs)}] {stem}")
        rc = run_one(jpg, mp4, out, verbose=verbose, indent="       ", quiet=not verbose)
        results.append((stem, out, rc, stale))
        if not verbose:
            size = os.path.getsize(out) if rc in (0, 1) and os.path.exists(out) else 0
            status = {0: "成功", 1: "校验失败", 2: "输入有误"}[rc]
            print(f"       -> {status}  {size:,} B")
        print()

    print("=" * 60)
    print(f"汇总：共 {len(pairs)} 组，成功 {sum(1 for r in results if r[2] == 0)} 组，"
          f"失败 {sum(1 for r in results if r[2] != 0)} 组")
    for stem, out, rc, stale in results:
        if rc == 2:
            note = "（未生成；该路径有上次遗留文件，请勿使用）" if stale else "（未生成任何文件）"
            print(f"  [FAIL] {stem:<32} {note}")
        else:
            mark = "OK  " if rc == 0 else "FAIL"
            tail = "" if rc == 0 else "（校验未通过，请勿使用）"
            print(f"  [{mark}] {stem:<32} -> {out}{tail}")
    if orphans:
        print("\n未处理（无法配对）：")
        for p, why in orphans:
            print(f"  [SKIP] {os.path.basename(p):<40} {why}")

    return 0 if all(r[2] == 0 for r in results) else 1


def main():
    # 本脚本位于 <项目根>/tools/；默认输入取 <项目根>/input/，输出到 <项目根>/out/
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_dir = os.path.join(root, "input")
    out_dir = os.path.join(root, "out")

    args = sys.argv[1:]
    verbose = False
    if "-v" in args or "--verbose" in args:
        verbose = True
        args = [a for a in args if a not in ("-v", "--verbose")]

    # 无参数：批量转换 input/ 下所有同名 JPG+MP4 组合
    if not args:
        return run_batch(in_dir, out_dir, verbose=verbose)

    if len(args) == 1 and args[0] in ("-h", "--help"):
        print("用法:\n"
              "  python tools/make_live.py                         批量：转换 input/ 下所有同名 JPG+MP4\n"
              "  python tools/make_live.py -v                      批量 + 每组逐条校验\n"
              "  python tools/make_live.py 图.jpg 视频.mp4          单组，输出到 out/图.jpg\n"
              "  python tools/make_live.py 图.jpg 视频.mp4 出.jpg   单组，指定输出路径\n"
              "\n"
              "  -v, --verbose   批量模式下也逐条打印每一项校验（默认只在失败时展开）")
        return 0

    if len(args) < 2:
        print("[错误] 参数不足。")
        print("       用法: python tools/make_live.py [图片] [视频] [输出]")
        print("       不带参数则批量转换 input/ 下所有同名 JPG+MP4 组合。")
        return 2

    jpg = args[0]
    mp4 = args[1]
    out = args[2] if len(args) > 2 else os.path.join(out_dir, os.path.basename(jpg))
    return run_one(jpg, mp4, out, verbose=True)


if __name__ == "__main__":
    sys.exit(main())
