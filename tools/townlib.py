# -*- coding: utf-8 -*-
"""町のデータ（data/town/c_*.json）を Python で読むための道具。HTML の中の読み方と同じ。

座標：x＝東へ m、z＝南へ m（原点は data/routes.json の origin：北緯 34.735°・東経 136.92°）。
タイルは 400m 四方、標高と森は 4m ごと。
"""
import base64
import json
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
GN, GS, TILE = 101, 4.0, 400.0

_origin = None


def origin():
    global _origin
    if _origin is None:
        _origin = json.load(open(os.path.join(DATA, "routes.json"), encoding="utf-8"))["origin"]
    return _origin


def to_xz(lat, lon):
    o = origin()
    return (lon - o["lon0"]) * o["kx"], -(lat - o["lat0"]) * o["kz"]


def to_ll(x, z):
    o = origin()
    return o["lat0"] - z / o["kz"], o["lon0"] + x / o["kx"]


def inflate(b64):
    return zlib.decompress(base64.b64decode(b64))


def read_polys(u8):
    o = 0
    (n,) = struct.unpack_from("<H", u8, o)
    o += 2
    polys = []
    for _ in range(n):
        nr = u8[o]
        o += 1
        rings = []
        for _ in range(nr):
            np_, x, z = struct.unpack_from("<Hhh", u8, o)
            o += 6
            ring = [(x / 10, z / 10)]
            for _ in range(np_ - 1):
                dx, dz = struct.unpack_from("<hh", u8, o)
                o += 4
                x += dx
                z += dz
                ring.append((x / 10, z / 10))
            rings.append(ring)
        polys.append(rings)
    return polys


def read_lines(u8):
    o = 0
    (n,) = struct.unpack_from("<H", u8, o)
    o += 2
    out = []
    for _ in range(n):
        np_, x, z = struct.unpack_from("<Hhh", u8, o)
        o += 6
        line = [(x / 10, z / 10)]
        for _ in range(np_ - 1):
            dx, dz = struct.unpack_from("<hh", u8, o)
            o += 4
            x += dx
            z += dz
            line.append((x / 10, z / 10))
        out.append(line)
    return out


def read_buildings(t):
    """[(種類, 高さ m, [(x, z), ...])]。種類：0 普通建物・1 普通無壁舎・2 堅ろう建物・3 堅ろう無壁舎（index.json の types）"""
    if not t.get("nb"):
        return []
    u8 = inflate(t["b"])
    o = 0
    out = []
    for _ in range(t["nb"]):
        n, ty, h = u8[o], u8[o + 1], u8[o + 2] / 4
        x, z = struct.unpack_from("<hh", u8, o + 3)
        o += 7
        P = [(x / 10, z / 10)]
        for _ in range(n - 1):
            dx, dz = struct.unpack_from("<hh", u8, o)
            o += 4
            x += dx
            z += dz
            P.append((x / 10, z / 10))
        out.append((ty, h, P))
    return out


def read_heights(t):
    raw = inflate(t["h"])
    a = struct.unpack("<%dh" % (len(raw) // 2), raw)
    H = [0.0] * (GN * GN)
    for i in range(GN):
        v = 0
        for j in range(GN):
            v += a[i * GN + j]
            H[i * GN + j] = v / 10
    return H


def read_forest(t):
    """100×100 の 0/1（4m ごと。行＝南へ、列＝東へ）"""
    fb = inflate(t["f"])
    return [[(fb[(r * 100 + c) >> 3] >> (7 - ((r * 100 + c) & 7))) & 1 for c in range(100)] for r in range(100)]


class Town:
    def __init__(self):
        self.index = json.load(open(os.path.join(DATA, "town", "index.json"), encoding="utf-8"))
        self.chunk_of = {}
        for c in self.index["chunks"]:
            for k in c["tiles"]:
                self.chunk_of[(k[0], k[1])] = c["f"]
        self._chunks = {}
        self._tiles = {}

    def keys(self):
        return list(self.chunk_of.keys())

    def tile(self, key):
        key = tuple(key)
        if key not in self._tiles:
            f = self.chunk_of.get(key)
            if f is None:
                return None
            if f not in self._chunks:
                self._chunks[f] = json.load(open(os.path.join(DATA, f), encoding="utf-8"))
                for t in self._chunks[f]["tiles"]:
                    self._tiles[(t["k"][0], t["k"][1])] = t
        return self._tiles.get(key)

    def heights(self, key):
        t = self.tile(key)
        if t is None:
            return None
        if "_H" not in t:
            t["_H"] = read_heights(t)
        return t["_H"]

    def h_at(self, x, z):
        i, j = math.floor(x / TILE), math.floor(z / TILE)
        H = self.heights((i, j))
        if H is None:
            return None
        fx, fz = (x - i * TILE) / GS, (z - j * TILE) / GS
        c, r = min(GN - 2, max(0, int(fx))), min(GN - 2, max(0, int(fz)))
        u, v = min(1, max(0, fx - c)), min(1, max(0, fz - r))
        a, b, d, e = H[r * GN + c], H[r * GN + c + 1], H[(r + 1) * GN + c], H[(r + 1) * GN + c + 1]
        return a + (b - a) * u + (d - a) * v if u + v <= 1 else e + (d - e) * (1 - u) + (b - e) * (1 - v)

    def buildings_near(self, x, z, R):
        """(種類, 高さ, [(x, z)…世界の座標])"""
        out = []
        for i in range(math.floor((x - R) / TILE), math.floor((x + R) / TILE) + 1):
            for j in range(math.floor((z - R) / TILE), math.floor((z + R) / TILE) + 1):
                t = self.tile((i, j))
                if t is None:
                    continue
                if "_B" not in t:
                    t["_B"] = read_buildings(t)
                for ty, h, P in t["_B"]:
                    W = [(i * TILE + p[0], j * TILE + p[1]) for p in P]
                    cx = sum(p[0] for p in W) / len(W)
                    cz = sum(p[1] for p in W) / len(W)
                    if math.hypot(cx - x, cz - z) <= R:
                        out.append((ty, h, W))
        return out


def in_poly(P, x, z):
    c = False
    n = len(P)
    j = n - 1
    for i in range(n):
        a, b = P[i], P[j]
        if (a[1] > z) != (b[1] > z) and x < (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
        j = i
    return c


def poly_area(P):
    s = 0
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        s += a[0] * b[1] - b[0] * a[1]
    return s / 2
