# -*- coding: utf-8 -*-
"""海っ子バスの経路が海のすぐそばを通る所に、護岸（海側のコンクリートの胸壁・のり面のブロック・砂浜）を置く。

経路（data/routes.json の全部の形）を 4m ごとに歩き、左右それぞれに、
  車道・歩道の端（町のデータの car・side の形）と、最初の海（標高 −0.5m 未満の格子）までの距離を調べる。
  海まで 28m 以内なら、そこに護岸を置く：
    ・胸壁：道路の端の 0.3m 外に、高さ 1.1m・厚さ 0.5m のコンクリートの壁（走行動画のとおり）
    ・海まで 9m 未満：胸壁の外は、間知ブロックののり面（海の中 −1.2m まで）
    ・9m 以上：胸壁の外は砂浜（海へゆるく下がる）
同じ所を何度も拾った点を 2m 以内で 1 つにまとめ、海を右に見て前へだけ進むように 1 本の列につなぎ、160m ごとに切って data/scenery.json に model "seawall" として登録する。

使い方： python tools/make_seawall.py
"""
import io
import json
import math
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import townlib as TL  # noqa: E402

ROOT = os.path.join(HERE, "..")
SP = os.path.join(ROOT, "data", "scenery.json")
STEP = 4.0
MAXD = 28.0
CHUNK = 160.0


class RoadMask:
    """タイルごとに、車道・歩道を 0.5m のマスに塗った表"""

    def __init__(self, T):
        self.T = T
        self.cache = {}

    def get(self, key):
        if key not in self.cache:
            t = self.T.tile(key)
            m = np.zeros((800, 800), np.uint8)
            if t is not None:
                for name in ("car", "side", "med", "alley"):
                    if not t.get(name):
                        continue
                    for rings in TL.read_polys(TL.inflate(t[name])):
                        for ri, ring in enumerate(rings):
                            P = np.array([[p[0] * 2, p[1] * 2] for p in ring], np.int32)
                            cv2.fillPoly(m, [P], 0 if ri else 1)
            self.cache[key] = m
        return self.cache[key]

    def road(self, x, z):
        i, j = math.floor(x / 400), math.floor(z / 400)
        m = self.get((i, j))
        c, r = int((x - i * 400) * 2), int((z - j * 400) * 2)
        return 0 <= r < 800 and 0 <= c < 800 and m[r, c] > 0


def main():
    T = TL.Town()
    RM = RoadMask(T)
    R = json.load(open(os.path.join(ROOT, "data", "routes.json"), encoding="utf-8"))
    # 経路の線分（重ならないように、4m ごとの点を 2m の格子で一つにまとめる）
    samples = {}
    for P in R["patterns"]:
        a = P["pts"]
        xy = [(a[i] / 10, a[i + 1] / 10) for i in range(0, len(a), 2)]
        acc = 0.0
        for i in range(len(xy) - 1):
            (ax, az), (bx, bz) = xy[i], xy[i + 1]
            L = math.hypot(bx - ax, bz - az)
            if L < 0.01:
                continue
            ux, uz = (bx - ax) / L, (bz - az) / L
            t = (STEP - acc) % STEP
            while t < L:
                x, z = ax + ux * t, az + uz * t
                key = (round(x / 3), round(z / 3))
                if key not in samples:
                    samples[key] = (x, z, ux, uz)
                t += STEP
            acc = (acc + L) % STEP
    print("経路の点", len(samples))
    hits = []
    for (x, z, ux, uz) in samples.values():
        for sd in (-1, 1):
            nx, nz = -uz * sd, ux * sd
            # 道路の端
            e = None
            for k in range(2, 60):
                d = k * 0.5
                if not RM.road(x + nx * d, z + nz * d):
                    e = d
                    break
            if e is None or e > 14:
                continue
            # 最初の海
            sea = None
            d = e
            while d < e + MAXD:
                h = T.h_at(x + nx * d, z + nz * d)
                if h is not None and h < -0.5:
                    sea = d
                    break
                d += 1.0
            if sea is None:
                continue
            # 間に建物があれば置かない
            blocked = False
            for ty, hh, Pb in T.buildings_near(x + nx * (e + sea) / 2, z + nz * (e + sea) / 2, 30):
                for f in (0.25, 0.5, 0.75):
                    q = e + (sea - e) * f
                    if TL.in_poly(Pb, x + nx * q, z + nz * q):
                        blocked = True
                        break
                if blocked:
                    break
            if blocked:
                continue
            hits.append({"x": x, "z": z, "nx": nx, "nz": nz, "e": e, "sea": sea})
    print("護岸の点", len(hits))
    # 壁の位置（道路の端の 0.3m 外）。経路の上り・下りや別の便の線から同じ所を何度も拾うので、
    # 2m 以内で向きのそろった点は 1 つにまとめる（まとめないと、少しずつずれた壁が何枚も重なって、薄い板の束に見える）
    W = []
    for h in hits:
        W.append({"x": h["x"] + h["nx"] * (h["e"] + 0.3), "z": h["z"] + h["nz"] * (h["e"] + 0.3), "nx": h["nx"], "nz": h["nz"], "d": h["sea"] - h["e"] - 0.3})
    cell = {}
    for i, p in enumerate(W):
        cell.setdefault((math.floor(p["x"] / 4), math.floor(p["z"] / 4)), []).append(i)

    def near(x, z, R):
        out = []
        for ci in range(math.floor((x - R) / 4), math.floor((x + R) / 4) + 1):
            for cj in range(math.floor((z - R) / 4), math.floor((z + R) / 4) + 1):
                out += cell.get((ci, cj), [])
        return out
    gone = [False] * len(W)
    M = []
    for i, p in enumerate(W):
        if gone[i]:
            continue
        grp = [j for j in near(p["x"], p["z"], 2.2) if not gone[j] and math.hypot(W[j]["x"] - p["x"], W[j]["z"] - p["z"]) < 2.0
               and W[j]["nx"] * p["nx"] + W[j]["nz"] * p["nz"] > 0.6]
        for j in grp:
            gone[j] = True
        n = len(grp)
        nx, nz = sum(W[j]["nx"] for j in grp), sum(W[j]["nz"] for j in grp)
        L = math.hypot(nx, nz) or 1
        M.append({"x": sum(W[j]["x"] for j in grp) / n, "z": sum(W[j]["z"] for j in grp) / n, "nx": nx / L, "nz": nz / L,
                  "d": min(W[j]["d"] for j in grp)})
    print("まとめた壁の点", len(M))
    cell = {}
    for i, p in enumerate(M):
        cell.setdefault((math.floor(p["x"] / 4), math.floor(p["z"] / 4)), []).append(i)
    # 列にまとめる：海を右に見て進む向き（t）に、前へ 1〜7m・横へ 1.8m 以内の、いちばん近い点へ進む（戻らない）
    used = [False] * len(M)
    runs = []

    def grow(run, sign):
        while True:
            p = run[-1]
            if len(run) >= 2:
                q0 = run[-2]
                tx, tz = p["x"] - q0["x"], p["z"] - q0["z"]
                L = math.hypot(tx, tz) or 1
                tx, tz = tx / L, tz / L
            else:
                tx, tz = -p["nz"] * sign, p["nx"] * sign
            best, bj = 1e9, -1
            for j in near(p["x"], p["z"], 7.5):
                q = M[j]
                if used[j] or q["nx"] * p["nx"] + q["nz"] * p["nz"] < 0.5:
                    continue
                dx, dz = q["x"] - p["x"], q["z"] - p["z"]
                al = dx * tx + dz * tz
                la = abs(-dx * tz + dz * tx)
                if not (0.8 < al < 7.0) or la > 1.8 + al * 0.15:
                    continue
                sc = al + la * 3
                if sc < best:
                    best, bj = sc, j
            if bj < 0:
                return
            used[bj] = True
            run.append(M[bj])

    order = sorted(range(len(M)), key=lambda i: (M[i]["x"], M[i]["z"]))
    for i in order:
        if used[i]:
            continue
        used[i] = True
        fw = [M[i]]
        grow(fw, 1)
        bw = [M[i]]
        grow(bw, -1)
        run = bw[::-1] + fw[1:]
        if len(run) >= 3:
            runs.append(run)
    print("列", len(runs), "長さ合計 %.0fm" % sum(sum(math.hypot(r[k + 1]["x"] - r[k]["x"], r[k + 1]["z"] - r[k]["z"]) for k in range(len(r) - 1)) for r in runs))
    # 160m ごとに切る
    S = json.load(io.open(SP, encoding="utf-8"))
    S["facades"] = [f for f in S["facades"] if f.get("model") != "seawall"]
    n = 0
    for r in runs:
        per = int(CHUNK / STEP)
        for c0 in range(0, len(r), per):
            part = r[max(0, c0 - 1):c0 + per]
            if len(part) < 2:
                continue
            pts = [[round(p["x"], 2), round(p["z"], 2), round(p["nx"], 3), round(p["nz"], 3), round(p["d"], 1)] for p in part]
            mx, mz = pts[len(pts) // 2][0] + pts[len(pts) // 2][2] * 2, pts[len(pts) // 2][1] + pts[len(pts) // 2][3] * 2
            S["facades"].append({"name": "護岸 %d" % n, "poly": [[mx, mz], [mx + 0.3, mz], [mx + 0.3, mz + 0.3], [mx, mz + 0.3]], "model": "seawall", "pts": pts})
            n += 1
    io.open(SP, "w", encoding="utf-8").write(json.dumps(S, ensure_ascii=False, indent=1) + "\n")
    print("登録した護岸", n)


if __name__ == "__main__":
    main()
