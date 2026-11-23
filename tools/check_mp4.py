#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深度校验 MP4：盒完整性 + 样本表一致性 + 所有样本字节范围是否落在 mdat 内。
用于判断「源视频本身是否完好可播」，以及拼接后视频区是否自洽。"""
import struct
import sys

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"dinf", b"edts", b"udta"}


def boxes(d, off, end):
    out = []
    while off + 8 <= end:
        size = struct.unpack(">I", d[off:off + 4])[0]
        typ = d[off + 4:off + 8]
        hdr = 8
        if size == 1:
            if off + 16 > end:
                break
            size = struct.unpack(">Q", d[off + 8:off + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr or off + size > end:
            out.append((typ, off, size, hdr, "BAD"))
            break
        out.append((typ, off, size, hdr, "ok"))
        if typ in CONTAINERS:
            out += boxes(d, off + hdr, off + size)
        elif typ == b"meta":
            out += boxes(d, off + hdr + 4, off + size)
        off += size
    return out


def full_box(d, off):
    """返回 (version, flags, payload_start)"""
    return d[off + 8], int.from_bytes(d[off + 9:off + 12], "big"), off + 12


def parse_trak(d, trak_off, trak_size):
    sub = boxes(d, trak_off + 8, trak_off + trak_size)
    info = {}
    for typ, off, size, hdr, _ in sub:
        if typ == b"tkhd":
            info["tkhd_off"] = off
        elif typ == b"mdia":
            for t2, o2, s2, h2, _ in boxes(d, off + hdr, off + size):
                if t2 == b"hdlr":
                    info["handler"] = d[o2 + 16:o2 + 20]
                elif t2 == b"mdhd":
                    v = d[o2 + 8]
                    if v == 0:
                        info["timescale"] = struct.unpack(">I", d[o2 + 20:o2 + 24])[0]
                        info["duration"] = struct.unpack(">I", d[o2 + 24:o2 + 28])[0]
                    else:
                        info["timescale"] = struct.unpack(">I", d[o2 + 28:o2 + 32])[0]
                        info["duration"] = struct.unpack(">Q", d[o2 + 32:o2 + 40])[0]
                elif t2 == b"minf":
                    for t3, o3, s3, h3, _ in boxes(d, o2 + h2, o2 + s2):
                        if t3 == b"stbl":
                            info["stbl"] = (o3, s3)
    return info


def read_table(d, off, size, typ):
    """解析 stsz / stsc / stts / co64 / stco / stss"""
    v = d[off + 8]
    if typ == b"stsz":
        fixed = struct.unpack(">I", d[off + 12:off + 16])[0]
        count = struct.unpack(">I", d[off + 16:off + 20])[0]
        if fixed:
            return [fixed] * count
        return list(struct.unpack(">%dI" % count, d[off + 20:off + 20 + 4 * count]))
    if typ in (b"stco", b"co64"):
        n = struct.unpack(">I", d[off + 12:off + 16])[0]
        if typ == b"stco":
            return list(struct.unpack(">%dI" % n, d[off + 16:off + 16 + 4 * n]))
        return list(struct.unpack(">%dQ" % n, d[off + 16:off + 16 + 8 * n]))
    if typ == b"stsc":
        n = struct.unpack(">I", d[off + 12:off + 16])[0]
        return [struct.unpack(">III", d[off + 16 + 12 * i:off + 28 + 12 * i]) for i in range(n)]
    if typ == b"stts":
        n = struct.unpack(">I", d[off + 12:off + 16])[0]
        return [struct.unpack(">II", d[off + 16 + 8 * i:off + 24 + 8 * i]) for i in range(n)]
    if typ == b"stss":
        n = struct.unpack(">I", d[off + 12:off + 16])[0]
        return list(struct.unpack(">%dI" % n, d[off + 16:off + 16 + 4 * n]))
    return None


def validate(path, base=0, label=""):
    d = open(path, "rb").read()
    total = len(d)
    print(f"===== {label or path}  文件 {total} B，视频区起点 base={base}")
    top = boxes(d, base, total)
    bad = [b for b in top if b[4] == "BAD"]
    print("  顶层盒：", [(b[0].decode("latin1"), b[1] - base, b[2]) for b in top])
    if bad:
        print("  !! 顶层盒损坏：", bad)
    moov = [b for b in top if b[0] == b"moov"]
    mdat = [b for b in top if b[0] == b"mdat"]
    if not moov or not mdat:
        print("  !! 缺 moov 或 mdat")
        return False
    mo = moov[0]
    md = mdat[0]
    mdat_start, mdat_end = md[1], md[1] + md[2]
    print(f"  moov @{mo[1]-base} size={mo[2]}   mdat @{md[1]-base} size={md[2]} 覆盖 [{mdat_start-base},{mdat_end-base})")
    ok = True
    traks = [b for b in boxes(d, mo[1] + mo[3], mo[1] + mo[2]) if b[0] == b"trak"]
    for i, tk in enumerate(traks):
        info = parse_trak(d, tk[1], tk[2])
        so, ss = info["stbl"]
        tbl = {}
        for t, o, s, h, _ in boxes(d, so + 8, so + ss):
            if t in (b"stsz", b"stsc", b"stts", b"co64", b"stco", b"stss"):
                tbl[t] = read_table(d, o, s, t)
        sizes = tbl.get(b"stsz", [])
        offsets = tbl.get(b"co64") or tbl.get(b"stco") or []
        stsc = tbl.get(b"stsc", [])
        stts = tbl.get(b"stts", [])
        handler = info.get("handler", b"????").decode("latin1")
        print(f"  -- trak#{i} handler={handler} timescale={info.get('timescale')} duration={info.get('duration')}"
              f" 样本数={len(sizes)} chunk数={len(offsets)}")
        # 用 stsc 展开每个 chunk 的样本数
        if stsc and sizes and offsets:
            per_chunk = []
            for ci in range(1, len(offsets) + 1):
                cnt = 0
                for k, (first, spc, sdi) in enumerate(stsc):
                    nxt = stsc[k + 1][0] if k + 1 < len(stsc) else 10 ** 9
                    if first <= ci < nxt:
                        cnt = spc
                        break
                per_chunk.append(cnt)
            si = 0
            bad_ranges = []
            for ci, cnt in enumerate(per_chunk):
                need = sum(sizes[si:si + cnt])
                si += cnt
                cstart = base + offsets[ci]
                cend = cstart + need
                if cstart < mdat_start or cend > mdat_end:
                    bad_ranges.append((ci, cstart - base, cend - base))
            print(f"     stsc 展开后样本合计={si}（应={len(sizes)}）"
                  f"  {'一致' if si == len(sizes) else '!! 不一致'}")
            if bad_ranges:
                ok = False
                print(f"     !! {len(bad_ranges)} 个 chunk 越出 mdat 范围，前 5 个：{bad_ranges[:5]}")
            else:
                print("     所有 chunk 字节范围均落在 mdat 内 ✓")
        if stts:
            total_samples = sum(c for c, _ in stts)
            dur = sum(c * dl for c, dl in stts)
            ts = info.get("timescale") or 1
            print(f"     stts 样本合计={total_samples} 时长={dur / ts:.3f}s")
            if total_samples != len(sizes):
                ok = False
                print("     !! stts 样本数与 stsz 不一致")
    # 检查 mdat 之后是否还有字节
    print(f"  mdat 结束位置 {mdat_end}，文件长度 {total}，尾部多余 {total - mdat_end} B")
    return ok


if __name__ == "__main__":
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    a = sys.argv[1:] or [os.path.join(root, "input", "IMG_20250816_143305.mp4")]
    for p in a:
        validate(p)
        print()
