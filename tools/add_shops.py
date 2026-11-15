# -*- coding: utf-8 -*-
"""沿道の店（コンビニ・ドラッグストア・ホームセンター・ガソリンスタンドなど）と学校を、主要施設の一覧（data/scenery.json）に足す。

店ごとに、町のデータの建物（at の点を含む建物）の形から「正面の壁の線」を決めて書きこむ。
  front：正面の壁の両端 [ax, az, bx, bz]（a → b を外から見て左 → 右）。指定した方位（facing）に一番近い向きの辺
  lot：正面の前の駐車場の奥行き（m）。正面から一番近い海っ子バスの経路までの距離から決める（最大 lotMax）
学校は「area」（敷地の形）で指定し、その中の建物をそれぞれ学校の校舎・体育館として描く（MODELS.school）。

店の場所と見た目は、2026-11-08 の走行動画（正面・左右）で確かめた。名前は動画の看板のとおり。
使い方： python tools/add_shops.py
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

# name, at（建物の中の点）, kind, brand, facing（正面の外向きの方位：北 0・東 90）, その他
SHOPS = [
    ("ファミリーマート 南知多内海店・やさい村 内海店", (-4741.0, -425.0), "conbini", "familymart", 0, {"sub": "yasaimura", "pole": [-4722.0, -463.0]}),
    ("ダイソー 知多内海店", (-4671.0, -492.0), "big", "daiso", 180, {"pole": [-4700.0, -470.0]}),
    ("スギ薬局 内海店", (-4686.0, -430.0), "drug", "sugi", 270, {"pole": [-4699.0, -458.0], "lotMax": 22}),
    ("ゲンキー 内海店", (-4637.0, -387.0), "drug", "genky", 0, {"pole": [-4630.0, -430.0]}),
    ("モスバーガー 南知多店", (-4609.3, -450.3), "mos", "mos", 180, {"pole": [-4600.0, -441.0]}),
    ("カインズ 美浜店", (206.0, -2703.0), "big", "cainz", 270, {"pole": [128.0, -2640.0], "lotMax": 60}),
    ("フィール 美浜店", (171.0, -2845.0), "big", "feel", 270, {"pole": [125.0, -2668.0], "lotMax": 60}),
    ("スズキアリーナ 美浜", (161.5, -2554.5), "dealer", "suzuki", 90, {"pole": [178.0, -2562.0]}),
    ("セブン-イレブン 南知多内海店", (-4401.3, -421.0), "conbini", "seven", None, {}),
    ("ファミリーマート 豊浜店", (1263.8, -0.0 + 2930.1), "conbini", "familymart", None, {}),
]
# 内海高校は、校舎（経路の北東の林の向こう）の形で指定し、種類にかかわらず 400㎡ 以上の建物を校舎・体育館にする
HIGH = ("内海高校", [[-2075.0, -3030.0], [-1950.0, -3030.0], [-1950.0, -2850.0], [-2075.0, -2850.0]])
SCHOOLS = [
    ("内海中学校", (-4260.0, -1231.0), 110),
    ("内海小学校", (-4529.0, -330.0), 100),
    ("河和小学校", (-761.0, -4127.0), 100),
    ("河和中学校", (-340.0, -3399.0), 110),
    ("豊浜小学校", (1112.0, 2733.0), 100),
]


def route_segments():
    R = json.load(open(os.path.join(ROOT, "data", "routes.json"), encoding="utf-8"))
    segs = set()
    for P in R["patterns"]:
        a = P["pts"]
        for i in range(0, len(a) - 2, 2):
            segs.add((a[i] / 10, a[i + 1] / 10, a[i + 2] / 10, a[i + 3] / 10))
    return list(segs)


def dist_route(segs, x, z):
    best = 1e9
    for ax, az, bx, bz in segs:
        dx, dz = bx - ax, bz - az
        L2 = dx * dx + dz * dz
        t = 0 if L2 == 0 else max(0, min(1, ((x - ax) * dx + (z - az) * dz) / L2))
        best = min(best, math.hypot(x - ax - t * dx, z - az - t * dz))
    return best


def find_building(T, x, z):
    for ty, h, P in T.buildings_near(x, z, 80):
        if TL.in_poly(P, x, z):
            return ty, h, P
    return None


def facing_to_route(segs, P):
    """建物の中心から一番近い経路の点の方位（北 0・東 90）"""
    cx = sum(p[0] for p in P) / len(P)
    cz = sum(p[1] for p in P) / len(P)
    best, bp = 1e9, None
    for ax, az, bx, bz in segs:
        dx, dz = bx - ax, bz - az
        L2 = dx * dx + dz * dz
        t = 0 if L2 == 0 else max(0, min(1, ((cx - ax) * dx + (cz - az) * dz) / L2))
        qx, qz = ax + t * dx, az + t * dz
        d = math.hypot(cx - qx, cz - qz)
        if d < best:
            best, bp = d, (qx, qz)
    return math.degrees(math.atan2(bp[0] - cx, -(bp[1] - cz))) % 360


def front_edge(P, facing):
    """方位 facing（外向き）に一番近い外向きの法線をもつ、長さ 4m 以上の辺。a → b は外から見て左 → 右"""
    ar = TL.poly_area(P)
    r = math.radians(facing)
    fx, fz = math.sin(r), -math.cos(r)
    best, bs = None, -9
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 4:
            continue
        nx, nz = (b[1] - a[1]) / L, -(b[0] - a[0]) / L
        if ar < 0:
            nx, nz = -nx, -nz
        dot = nx * fx + nz * fz
        sc = dot + (L * 0.02 if dot > 0.5 else 0)
        if sc > bs:
            bs, best = sc, (a, b, nx, nz)
    a, b, nx, nz = best
    # 外から見て左 → 右：右の向き r = (−nz, nx)… Kit の +Z（手前）が外向きの法線になるように a・b を並べる
    dx, dz = b[0] - a[0], b[1] - a[1]
    if (-dz) * nx + dx * nz < 0:
        a, b = b, a
    return [round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2)], (nx, nz)


def main():
    T = TL.Town()
    segs = route_segments()
    S = json.load(io.open(SP, encoding="utf-8"))
    S["facades"] = [f for f in S["facades"] if f.get("model") not in ("shop", "school")]
    for name, at, kind, brand, facing, extra in SHOPS:
        hit = find_building(T, *at)
        if not hit:
            print("建物が見つからない：", name)
            continue
        ty, h, P = hit
        if facing is None:
            facing = facing_to_route(segs, P)
        fr, (nx, nz) = front_edge(P, facing)
        mx, mz = (fr[0] + fr[2]) / 2, (fr[1] + fr[3]) / 2
        # 正面から道路の方へ進んで、経路まで何 m あるか（1m きざみ）
        lot = 0
        for d in range(1, int(extra.get("lotMax", 40)) + 1):
            if dist_route(segs, mx + nx * d, mz + nz * d) < 6.5:
                break
            lot = d
        f = {"name": name, "at": [at[0], at[1]], "model": "shop", "kind": kind, "brand": brand, "front": fr, "lot": max(0, lot - 1), "h": h}
        for k, v in extra.items():
            if k != "lotMax":
                f[k] = v
        if "pole" not in f:
            d = max(1.5, f["lot"] - 1.0)
            f["pole"] = [round(fr[0] + nx * d - (fr[2] - fr[0]) * 0.05, 1), round(fr[1] + nz * d - (fr[3] - fr[1]) * 0.05, 1)]
        S["facades"].append(f)
        print("%s：建物 %d㎡・高さ %.1fm・正面 %.1fm・駐車場の奥行き %dm" % (name, abs(TL.poly_area(P)), h, math.hypot(fr[2] - fr[0], fr[3] - fr[1]), f["lot"]))
    S["facades"].append({"name": HIGH[0], "area": HIGH[1], "model": "school", "anyType": True, "minArea": 400, "label": "愛知県立内海高等学校"})
    for name, c, R in SCHOOLS:
        ring = [[round(c[0] + R * math.cos(i / 16 * math.pi * 2), 1), round(c[1] + R * math.sin(i / 16 * math.pi * 2), 1)] for i in range(16)]
        n = 0
        for ty, h, P in T.buildings_near(c[0], c[1], R):
            if ty == 2 or abs(TL.poly_area(P)) > 500:
                n += 1
        S["facades"].append({"name": name, "area": ring, "model": "school", "minArea": 250, "label": "南知多町立" + name})
        print("%s：大きな建物 %d 棟" % (name, n))
    io.open(SP, "w", encoding="utf-8").write(json.dumps(S, ensure_ascii=False, indent=1) + "\n")
    print("scenery", len(S["facades"]))


if __name__ == "__main__":
    main()
