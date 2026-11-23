#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出 JPG 全部 EXIF/APP 段标签，以及 MP4 的 meta 盒内容。"""
import struct
import sys

TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
TYPE_NAME = {1: "BYTE", 2: "ASCII", 3: "SHORT", 4: "LONG", 5: "RATIONAL",
             6: "SBYTE", 7: "UNDEF", 8: "SSHORT", 9: "SLONG", 10: "SRATIONAL",
             11: "FLOAT", 12: "DOUBLE"}

TAGS = {
    0x0100: "ImageWidth", 0x0101: "ImageLength", 0x0102: "BitsPerSample",
    0x0103: "Compression", 0x0106: "PhotometricInterp", 0x010E: "ImageDescription",
    0x010F: "Make", 0x0110: "Model", 0x0112: "Orientation", 0x011A: "XResolution",
    0x011B: "YResolution", 0x011C: "PlanarConfig", 0x0128: "ResolutionUnit",
    0x0131: "Software", 0x0132: "DateTime", 0x013B: "Artist",
    0x013E: "WhitePoint", 0x013F: "PrimaryChromaticities", 0x0211: "YCbCrCoefficients",
    0x0212: "YCbCrSubSampling", 0x0213: "YCbCrPositioning", 0x0214: "ReferenceBlackWhite",
    0x8298: "Copyright", 0x829A: "ExposureTime", 0x829D: "FNumber",
    0x8769: "ExifIFD", 0x8822: "ExposureProgram", 0x8825: "GPSIFD", 0x8827: "ISO",
    0x882A: "TimeZoneOffset", 0x9000: "ExifVersion", 0x9003: "DateTimeOriginal",
    0x9004: "DateTimeDigitized", 0x9010: "OffsetTime", 0x9011: "OffsetTimeOriginal",
    0x9012: "OffsetTimeDigitized", 0x9101: "ComponentsConfig", 0x9102: "CompressedBitsPerPixel",
    0x9201: "ShutterSpeedValue", 0x9202: "ApertureValue", 0x9203: "BrightnessValue",
    0x9204: "ExposureBiasValue", 0x9205: "MaxApertureValue", 0x9206: "SubjectDistance",
    0x9207: "MeteringMode", 0x9208: "LightSource", 0x9209: "Flash", 0x920A: "FocalLength",
    0x9214: "SubjectArea", 0x927C: "MakerNote", 0x9286: "UserComment", 0x9290: "SubSecTime",
    0x9291: "SubSecTimeOriginal", 0x9292: "SubSecTimeDigitized", 0xA000: "FlashpixVersion",
    0xA001: "ColorSpace", 0xA002: "PixelXDimension", 0xA003: "PixelYDimension",
    0xA004: "RelatedSoundFile", 0xA005: "InteropIFD", 0xA20E: "FocalPlaneXRes",
    0xA20F: "FocalPlaneYRes", 0xA210: "FocalPlaneResUnit", 0xA217: "SensingMethod",
    0xA300: "FileSource", 0xA301: "SceneType", 0xA401: "CustomRendered",
    0xA402: "ExposureMode", 0xA403: "WhiteBalance", 0xA404: "DigitalZoomRatio",
    0xA405: "FocalLengthIn35mm", 0xA406: "SceneCaptureType", 0xA407: "GainControl",
    0xA408: "Contrast", 0xA409: "Saturation", 0xA40A: "Sharpness",
    0xA40B: "DeviceSettingDesc", 0xA40C: "SubjectDistanceRange", 0xA420: "ImageUniqueID",
    0xA430: "CameraOwnerName", 0xA431: "BodySerialNumber", 0xA432: "LensSpecification",
    0xA433: "LensMake", 0xA434: "LensModel", 0xA435: "LensSerialNumber",
    0x0000: "GPSVersionID", 0x0001: "GPSLatitudeRef", 0x0002: "GPSLatitude",
    0x0003: "GPSLongitudeRef", 0x0004: "GPSLongitude", 0x0005: "GPSAltitudeRef",
    0x0006: "GPSAltitude", 0x0007: "GPSTimeStamp", 0x0008: "GPSSatellites",
    0x0009: "GPSStatus", 0x000A: "GPSMeasureMode", 0x000B: "GPSDOP",
    0x000C: "GPSSpeedRef", 0x000D: "GPSSpeed", 0x000E: "GPSTrackRef",
    0x000F: "GPSTrack", 0x0010: "GPSImgDirectionRef", 0x0011: "GPSImgDirection",
    0x0012: "GPSMapDatum", 0x0013: "GPSDestLatitudeRef", 0x0014: "GPSDestLatitude",
    0x0015: "GPSDestLongitudeRef", 0x0016: "GPSDestLongitude", 0x0017: "GPSDestBearingRef",
    0x0018: "GPSDestBearing", 0x0019: "GPSDestDistanceRef", 0x001A: "GPSDestDistance",
    0x001B: "GPSProcessingMethod", 0x001C: "GPSAreaInformation", 0x001D: "GPSDateStamp",
    0x001E: "GPSDifferential", 0x001F: "GPSHPositioningError",
}


def jpeg_segments(d):
    segs = []
    i = 2
    n = len(d)
    while i < n - 1:
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7 or m == 0x01:
            segs.append((i, m, 0))
            i += 2
            continue
        if i + 4 > n:
            break
        L = struct.unpack(">H", d[i + 2:i + 4])[0]
        segs.append((i, m, L))
        if m == 0xDA:
            break
        i += 2 + L
    return segs


def read_ifd(t, off, endian, label):
    out = []
    if off + 2 > len(t):
        return out, 0
    cnt = struct.unpack(endian + "H", t[off:off + 2])[0]
    if cnt > 512:
        print(f"  [{label}] @{off} count={cnt} 异常，跳过")
        return out, 0
    for k in range(cnt):
        p = off + 2 + 12 * k
        if p + 12 > len(t):
            break
        tag, typ, n = struct.unpack(endian + "HHI", t[p:p + 8])
        val = t[p + 8:p + 12]
        sz = TYPE_SIZE.get(typ, 1) * n
        if sz > 4:
            vo = struct.unpack(endian + "I", val)[0]
            raw = t[vo:vo + sz] if vo + sz <= len(t) else b""
        else:
            raw = val[:sz]
        out.append((tag, typ, n, raw))
        name = TAGS.get(tag, f"0x{tag:04X}")
        print(f"  [{label}] 0x{tag:04X} {name:<24} type={typ}({TYPE_NAME.get(typ,'?')}) n={n} raw={raw[:48]!r}"
              + (f" ...({len(raw)}B)" if len(raw) > 48 else ""))
    nxt = struct.unpack(endian + "I", t[off + 2 + 12 * cnt:off + 6 + 12 * cnt])[0] if off + 6 + 12 * cnt <= len(t) else 0
    return out, nxt


def dump_jpg(path):
    d = open(path, "rb").read()
    print(f"===== {path} ({len(d)} B)")
    for off, m, L in jpeg_segments(d):
        tag = f"APP{m-0xE0}" if 0xE0 <= m <= 0xEF else f"0x{m:02X}"
        print(f"  @{off} {tag} len={L} head={d[off+4:off+4+24]!r}")
    # 找 EXIF APP1
    for off, m, L in jpeg_segments(d):
        if m == 0xE1 and d[off + 4:off + 10] == b"Exif\x00\x00":
            t = d[off + 10:off + 2 + L]
            endian = "<" if t[:2] == b"II" else ">"
            print(f"  EXIF @{off} len={L} endian={'II' if endian=='<' else 'MM'} tiff_len={len(t)}")
            ifd0, nxt = read_ifd(t, struct.unpack(endian + "I", t[4:8])[0], endian, "IFD0")
            for tg, ty, n, raw in ifd0:
                if tg == 0x8769:
                    o = struct.unpack(endian + "I", raw[:4])[0]
                    read_ifd(t, o, endian, "ExifIFD")
                if tg == 0x8825:
                    o = struct.unpack(endian + "I", raw[:4])[0]
                    read_ifd(t, o, endian, "GPS")
            if nxt:
                read_ifd(t, nxt, endian, "IFD1")
    print()


def dump_meta(path):
    d = open(path, "rb").read()
    print(f"===== meta of {path}")

    def walk(off, end, depth=0):
        while off + 8 <= end:
            size = struct.unpack(">I", d[off:off + 4])[0]
            typ = d[off + 4:off + 8]
            if size < 8 or off + size > end:
                return
            print("  " * depth + f"{typ.decode('latin1')} @{off} size={size} body={d[off+8:off+min(size,200)]!r}")
            if typ in (b"ilst", b"moov", b"meta", b"udta", b"trak", b"mdia"):
                start = off + 12 if typ == b"meta" else off + 8
                walk(start, off + size, depth + 1)
            off += size

    idx = d.find(b"meta")
    while idx > 0:
        off = idx - 4
        size = struct.unpack(">I", d[off:off + 4])[0]
        print(f"  -- meta candidate @{off} size={size}")
        walk(off + 12, off + size, 1)
        idx = d.find(b"meta", idx + 1)
        if idx > 3000:
            break
    print()


import os
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_args = sys.argv[1:] or [
    os.path.join(_root, "input", "IMG_20250816_143305.jpg"),
    os.path.join(_root, "input", "IMG_20250816_143305.mp4"),
]
for p in _args:
    if p.lower().endswith((".jpg", ".jpeg")):
        dump_jpg(p)
    else:
        dump_meta(p)
