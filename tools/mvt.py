# -*- coding: utf-8 -*-
"""Mapbox Vector Tile（.pbf）を読む最小限の道具（外部ライブラリなし）。

国土地理院の「地理院地図 Vector」のタイルを読むために使う。
decode(bytes) -> {レイヤー名: [ {"type": 1|2|3, "props": {...}, "geom": [[(x, y), ...], ...]} ]}
座標はタイルの中の値（0〜extent）。extent は layer_extent(bytes) で分かる（ふつう 4096）。
"""
import struct


def _varint(b, i):
    r = 0
    s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if c < 0x80:
            return r, i
        s += 7


def _fields(b):
    i = 0
    n = len(b)
    while i < n:
        key, i = _varint(b, i)
        f, w = key >> 3, key & 7
        if w == 0:
            v, i = _varint(b, i)
        elif w == 1:
            v = b[i:i + 8]
            i += 8
        elif w == 2:
            ln, i = _varint(b, i)
            v = b[i:i + ln]
            i += ln
        elif w == 5:
            v = b[i:i + 4]
            i += 4
        else:
            raise ValueError("wire type %d" % w)
        yield f, w, v


def _zz(v):
    return (v >> 1) ^ -(v & 1)


def _value(b):
    for f, w, v in _fields(b):
        if f == 1:
            return v.decode("utf-8", "replace")
        if f == 2:
            return struct.unpack("<f", v)[0]
        if f == 3:
            return struct.unpack("<d", v)[0]
        if f in (4, 5):
            return v if v < (1 << 63) else v - (1 << 64)
        if f == 6:
            return _zz(v)
        if f == 7:
            return bool(v)
    return None


def _packed(b):
    out = []
    i = 0
    while i < len(b):
        v, i = _varint(b, i)
        out.append(v)
    return out


def _geom(cmds):
    parts = []
    cur = []
    x = y = 0
    i = 0
    while i < len(cmds):
        c = cmds[i]
        i += 1
        cid, cnt = c & 7, c >> 3
        if cid == 1:        # MoveTo
            for _ in range(cnt):
                if cur:
                    parts.append(cur)
                x += _zz(cmds[i])
                y += _zz(cmds[i + 1])
                i += 2
                cur = [(x, y)]
        elif cid == 2:      # LineTo
            for _ in range(cnt):
                x += _zz(cmds[i])
                y += _zz(cmds[i + 1])
                i += 2
                cur.append((x, y))
        elif cid == 7:      # ClosePath
            if cur:
                cur.append(cur[0])
    if cur:
        parts.append(cur)
    return parts


def decode(data):
    layers = {}
    for f, w, v in _fields(data):
        if f != 3:
            continue
        name = None
        keys = []
        vals = []
        feats = []
        for f2, w2, v2 in _fields(v):
            if f2 == 1:
                name = v2.decode("utf-8")
            elif f2 == 2:
                feats.append(v2)
            elif f2 == 3:
                keys.append(v2.decode("utf-8"))
            elif f2 == 4:
                vals.append(_value(v2))
        out = []
        for fb in feats:
            tags = []
            gt = 0
            cmds = []
            for f3, w3, v3 in _fields(fb):
                if f3 == 2:
                    tags = _packed(v3)
                elif f3 == 3:
                    gt = v3
                elif f3 == 4:
                    cmds = _packed(v3)
            props = {keys[tags[k]]: vals[tags[k + 1]] for k in range(0, len(tags) - 1, 2)}
            out.append({"type": gt, "props": props, "geom": _geom(cmds)})
        layers[name] = out
    return layers


def layer_extent(data):
    ext = {}
    for f, w, v in _fields(data):
        if f != 3:
            continue
        name = None
        e = 4096
        for f2, w2, v2 in _fields(v):
            if f2 == 1:
                name = v2.decode("utf-8")
            elif f2 == 5:
                e = v2
        ext[name] = e
    return ext
