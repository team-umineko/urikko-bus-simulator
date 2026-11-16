# -*- coding: utf-8 -*-
"""海っ子バスの経路から見える自然の海岸に、岩場（波打ちぎわの岩）を置く。

OpenStreetMap の海岸線（natural=coastline）を 4m ごとに歩き、
  ・経路から 70m より遠い所
  ・防波堤・桟橋・護岸（man_made=breakwater / pier / embankment）から 20m 以内
  ・砂浜（natural=beach）の中
  ・make_seawall.py の護岸（data/scenery.json の model "seawall"）の先から 14m 以内
はとばし、残りの所を、海の向き（海岸線の右）といっしょに記録する。
続く所を 1 本の列にまとめ、120m ごとに切って data/scenery.json に model "rocks" として登録する。

使い方： python tools/make_rocks.py <OSM の海岸の JSON（Overpass の出力）>
  出典：OpenStreetMap（© OpenStreetMap contributors）
"""
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import townlib as TL  # noqa: E402

ROOT = os.path.join(HERE, "..")
SP = os.path.join(ROOT, "data", "scenery.json")
STEP = 4.0
NEAR_ROUTE = 70.0
CHUNK = 120.0


class Grid:
    """点の近さを速く調べるための格子"""

    def __init__(self, pts, cell=25.0):
        self.c = cell
        self.g = {}
        for p in pts:
            self.g.setdefault((int(p[0] // cell), int(p[1] // cell)), []).append(p)

    def near(self, x, z, r):
        n = int(math.ceil(r / self.c))
        i0, j0 = int(x // self.c), int(z // self.c)
        for i in range(i0 - n, i0 + n + 1):
            for j in range(j0 - n, j0 + n + 1):
                for p in self.g.get((i, j), ()):
                    if (p[0] - x) ** 2 + (p[1] - z) ** 2 < r * r:
                        return True
        return False


def densify(P, step):
    out = []
    for i in range(len(P) - 1):
        (ax, az), (bx, bz) = P[i], P[i + 1]
        L = math.hypot(bx - ax, bz - az)
        n = max(1, int(L // step))
        for k in range(n):
            out.append((ax + (bx - ax) * k / n, az + (bz - az) * k / n))
    out.append(P[-1])
    return out


def main():
    src = sys.argv[1]
    d = json.load(io.open(src, encoding="utf-8"))
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in d["elements"] if e["type"] == "node"}
    ways = []
    for e in d["elements"]:
        if e["type"] != "way":
            continue
        pts = [TL.to_xz(*nodes[n]) for n in e.get("nodes", []) if n in nodes]
        if not pts and "geometry" in e:
            pts = [TL.to_xz(g["lat"], g["lon"]) for g in e["geometry"]]
        if len(pts) >= 2:
            ways.append((e.get("tags", {}), pts))
    print("way", len(ways))
    R = json.load(io.open(os.path.join(ROOT, "data", "routes.json"), encoding="utf-8"))
    rpts = []
    for P in R["patterns"]:
        a = P["pts"]
        rpts += densify([(a[i] / 10, a[i + 1] / 10) for i in range(0, len(a), 2)], 8)
    RG = Grid(rpts, 40)
    MM = Grid([p for t, P in ways if t.get("man_made") in ("breakwater", "pier", "embankment") for p in densify(P, 4)], 25)
    beaches = [P for t, P in ways if t.get("natural") == "beach"]
    S = json.load(io.open(SP, encoding="utf-8"))
    SW = Grid([(p[0] + p[2] * p[4], p[1] + p[3] * p[4]) for f in S["facades"] if f.get("model") == "seawall" for p in f["pts"]], 25)
    T = TL.Town()
    hits = []
    for t, P in ways:
        if t.get("natural") != "coastline":
            continue
        Q = densify(P, STEP)
        for i in range(len(Q) - 1):
            (x, z), (x2, z2) = Q[i], Q[i + 1]
            L = math.hypot(x2 - x, z2 - z)
            if L < 0.5:
                continue
            if not RG.near(x, z, NEAR_ROUTE) or MM.near(x, z, 20) or SW.near(x, z, 14):
                continue
            if any(TL.in_poly(B, x, z) for B in beaches):
                continue
            nx, nz = -(z2 - z) / L, (x2 - x) / L          # 海岸線の右（海の側）
            hl, hs = T.h_at(x - nx * 6, z - nz * 6), T.h_at(x + nx * 6, z + nz * 6)
            if hl is not None and hs is not None and hl < hs:   # 向きが逆なら直す
                nx, nz = -nx, -nz
            hits.append((x, z, nx, nz, i == 0))
    print("岩場の点", len(hits))
    # 道路（車道・歩道・路地）にかからないように：岩は、点から海の側へ o0〜o0+6.5m・岸にそって ±1.75m の所に置き、
    # 大きいものは半径 2.7m ほどある。その範囲が道路から 2m 以上はなれる o0（−1.5m から 0.5m ずつ海の側へ）を点ごとに決める。
    # 6m ずらしてもだめな点（道路が海ぎわを通る所）には岩を置かない
    from make_seawall import RoadMask
    RM = RoadMask(T)
    kept = []
    for (x, z, nx, nz, first) in hits:
        o0 = -1.5
        while o0 <= 6.0:
            bad = False
            o = o0 - 4.7
            while o <= o0 + 6.5 + 4.7 and not bad:
                t = -6.5
                while t <= 6.5:
                    if RM.road(x + nx * o - nz * t, z + nz * o + nx * t):
                        bad = True
                        break
                    t += 0.5
                o += 0.5
            if not bad:
                break
            o0 += 0.5
        if o0 <= 6.0:
            kept.append((x, z, nx, nz, first, o0))
    print("道路にかからない点", len(kept), "（はなした点", sum(1 for k in kept if k[5] > -1.5), "）")
    hits = kept
    # 続く点を列に（4.5m より離れたら切る）、120m ごとに分ける
    runs, cur = [], []
    for h in hits:
        if cur and (math.hypot(h[0] - cur[-1][0], h[1] - cur[-1][1]) > STEP * 1.6 or len(cur) * STEP >= CHUNK):
            runs.append(cur)
            cur = []
        cur.append(h)
    if cur:
        runs.append(cur)
    runs = [r for r in runs if len(r) >= 3]
    S["facades"] = [f for f in S["facades"] if f.get("model") != "rocks"]
    for n, r in enumerate(runs):
        pts = [[round(p[0], 2), round(p[1], 2), round(p[2], 3), round(p[3], 3), p[5]] for p in r]
        mx, mz = pts[len(pts) // 2][0], pts[len(pts) // 2][1]
        S["facades"].append({"name": "岩場 %d" % n, "poly": [[mx, mz], [mx + 0.3, mz], [mx + 0.3, mz + 0.3], [mx, mz + 0.3]], "model": "rocks", "pts": pts})
    io.open(SP, "w", encoding="utf-8").write(json.dumps(S, ensure_ascii=False, indent=1) + "\n")
    print("登録した岩場", len(runs), "長さ %.0fm" % (sum(len(r) for r in runs) * STEP))


if __name__ == "__main__":
    main()
