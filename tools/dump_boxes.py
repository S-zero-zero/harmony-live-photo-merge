#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比源视频与官方华为样本的元数据细节：ftyp、mvhd、tkhd、gnre、meta、avcC/SPS。"""
import struct
import sys
import datetime

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"dinf", b"edts", b"udta"}


def boxes(d, off, end, depth=0):
    out = []
    while off + 8 <= end:
        size = struct.unpack(">I", d[off:off + 4])[0]
        typ = d[off + 4:off + 8]
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", d[off + 8:off + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr or off + size > end:
            break
        out.append((typ, off, size, hdr, depth))
        if typ in CONTAINERS:
            out += boxes(d, off + hdr, off + size, depth + 1)
        elif typ == b"meta":
            out += boxes(d, off + hdr + 4, off + size, depth + 1)
        off += size
    return out


def to_dt(t):
    if t == 0:
        return "0"
    try:
        return (datetime.datetime(1904, 1, 1) + datetime.timedelta(seconds=t)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return "?"


def sps_dims(sps):
    rb = bytearray()
    i = 0
    while i < len(sps):
        if i + 2 < len(sps) and sps[i] == 0 and sps[i + 1] == 0 and sps[i + 2] == 3:
            rb += sps[i:i + 2]
            i += 3
        else:
            rb.append(sps[i])
            i += 1
    bits = []
    for b in rb:
        for k in range(7, -1, -1):
            bits.append((b >> k) & 1)
    pos = 0

    def u(n):
        nonlocal pos
        v = 0
        for _ in range(n):
            v = (v << 1) | bits[pos]
            pos += 1
        return v

    def ue():
        nonlocal pos
        z = 0
        while pos < len(bits) and bits[pos] == 0:
            z += 1
            pos += 1
        pos += 1
        return (1 << z) - 1 + (u(z) if z else 0)

    def se():
        k = ue()
        return (k + 1) // 2 if k % 2 else -(k // 2)

    profile = u(8)
    u(8)
    u(8)
    ue()
    chroma = 1
    if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        chroma = ue()
        if chroma == 3:
            u(1)
        ue()
        ue()
        u(1)
        if u(1):
            for i in range(8 if chroma != 3 else 12):
                if u(1):
                    last = 8
                    nxt = 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt != 0:
                            nxt = (last + se() + 256) % 256
                        last = nxt if nxt != 0 else last
    ue()
    poc = ue()
    if poc == 0:
        ue()
    elif poc == 1:
        u(1)
        se()
        se()
        n = ue()
        for _ in range(n):
            se()
    ue()
    u(1)
    w_mbs = ue() + 1
    h_map = ue() + 1
    fmo = u(1)
    if not fmo:
        u(1)
    u(1)
    cl = cr = ct = cb = 0
    if u(1):
        cl, cr, ct, cb = ue(), ue(), ue(), ue()
    sw = 1 if chroma == 0 else 2
    sh = 1 if chroma == 0 else 2
    w = w_mbs * 16 - (cl + cr) * sw
    h = h_map * 16 * (2 - fmo) - (ct + cb) * sh * (2 - fmo)
    return w, h, profile


def report(path):
    d = open(path, "rb").read()
    print(f"===== {path}  ({len(d)} B)")
    bs = boxes(d, 0, len(d))

    # ftyp
    for typ, off, size, hdr, dep in bs:
        if typ == b"ftyp" and dep == 0:
            body = d[off + 8:off + size]
            major = body[:4]
            minor = struct.unpack(">I", body[4:8])[0]
            brands = [body[i:i + 4].decode("latin1") for i in range(8, len(body), 4)]
            print(f"  ftyp @{off} size={size} major={major.decode('latin1')} minor={minor} compatible={brands}")
            break

    for typ, off, size, hdr, dep in bs:
        if typ == b"mvhd":
            v = d[off + 8]
            if v == 0:
                ct, mt, ts, dur = struct.unpack(">IIII", d[off + 12:off + 28])
                rate = struct.unpack(">I", d[off + 20:off + 24])[0]
            else:
                ct, mt = struct.unpack(">QQ", d[off + 12:off + 28])
                ts, dur = struct.unpack(">IQ", d[off + 28:off + 40])
                rate = struct.unpack(">I", d[off + 32:off + 36])[0]
            print(f"  mvhd v={v} created={to_dt(ct)} modified={to_dt(mt)} timescale={ts} dur={dur} ({dur/ts:.3f}s) rate={rate/65536}")
        elif typ == b"gnre":
            print(f"  gnre @{off} size={size} body={d[off+8:off+size]!r}")
        elif typ == b"tkhd":
            v = d[off + 8]
            if v == 0:
                ct, mt, tid = struct.unpack(">III", d[off + 12:off + 24])
                dur = struct.unpack(">I", d[off + 28:off + 32])[0]
                moff = off + 52
                woff = moff + 36
            else:
                ct = struct.unpack(">Q", d[off + 12:off + 20])[0]
                mt = struct.unpack(">Q", d[off + 20:off + 28])[0]
                tid = struct.unpack(">I", d[off + 28:off + 32])[0]
                dur = struct.unpack(">Q", d[off + 36:off + 44])[0]
                moff = off + 64
                woff = moff + 36
            mat = struct.unpack(">9i", d[moff:moff + 36])
            w, h = struct.unpack(">II", d[woff:woff + 8])
            print(f"  tkhd @{off} v={v} id={tid} created={to_dt(ct)} dur={dur}"
                  f" matrix={list(mat)} size={w/65536:.0f}x{h/65536:.0f} flags={d[off+9:off+12].hex()}")
        elif typ == b"hdlr":
            print(f"  hdlr @{off} handler={d[off+16:off+20].decode('latin1')} name={d[off+32:off+size]!r}")
        elif typ == b"meta" and dep == 1:
            print(f"  meta @{off} size={size} head={d[off+8:off+12].hex()}")
            for t2, o2, s2, h2, dp2 in boxes(d, off + 12, off + size):
                print(f"    {t2.decode('latin1')} @{o2} size={s2} {d[o2+8:o2+min(s2,64)]!r}")
        elif typ == b"avcC":
            body = d[off + 8:off + size]
            print(f"  avcC @{off} size={size} profile={body[1]} compat={body[2]:02x} level={body[3]}"
                  f" lengthSizeMinusOne={body[4]&3} hex={body.hex()}")
            p = 5
            n = body[p] & 0x1F
            p += 1
            for k in range(n):
                l = struct.unpack(">H", body[p:p + 2])[0]
                p += 2
                sps = body[p:p + l]
                p += l
                w, h, prof = sps_dims(sps)
                print(f"    SPS#{k} len={l} -> {w}x{h} profile={prof}")
            np_ = body[p]
            p += 1
            for k in range(np_):
                l = struct.unpack(">H", body[p:p + 2])[0]
                p += 2 + l
                print(f"    PPS#{k} len={l}")
        elif typ == b"stss":
            n = struct.unpack(">I", d[off + 12:off + 16])[0]
            vals = struct.unpack(">%dI" % min(n, 8), d[off + 16:off + 16 + 4 * min(n, 8)])
            print(f"  stss 条目={n} 前几个={vals}")
        elif typ == b"elst":
            v = d[off + 8]
            n = struct.unpack(">I", d[off + 12:off + 16])[0]
            segs = []
            for i in range(n):
                if v == 0:
                    segs.append(struct.unpack(">IiHH", d[off + 16 + 12 * i:off + 28 + 12 * i]))
                else:
                    segs.append(struct.unpack(">QqHH", d[off + 16 + 20 * i:off + 36 + 20 * i]))
            print(f"  elst v={v} {segs}")
    print(f"  末尾 32 字节: {d[-32:].hex()}")
    print()


import os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_args = sys.argv[1:] or [
    os.path.join(_root, "input", "IMG_20250816_143305.mp4"),
    os.path.join(_root, "ref", "HUAWEI_extracted_video.mp4"),
]
for p in _args:
    report(p)
