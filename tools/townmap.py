# -*- coding: utf-8 -*-
"""町のデータ（建物・道路）と海っ子バスの経路を、番号つきの地図にする。建物の場所・向きを調べるための下調べ用。

使い方： python tools/townmap.py <中心 x> <中心 z> <半径 m> <出力 PNG> [画像の大きさ=1400]
        python tools/townmap.py ll <緯度> <経度> <半径 m> <出力 PNG>
  建物には番号を振る（中心から近い順）。標準出力に、番号・中心の座標・面積・高さ・種類・角の数を出す。
  上が北。目盛りは 50m ごと（x＝東へ、z＝南へ）。
"""
import json
import math
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import townlib as TL  # noqa: E402


def main():
    a = sys.argv[1:]
    if a[0] == "ll":
        cx, cz = TL.to_xz(float(a[1]), float(a[2]))
        a = a[1:]
    else:
        cx, cz = float(a[0]), float(a[1])
    R, out = float(a[2]), a[3]
    S = int(a[4]) if len(a) > 4 else 1400
    k = S / (2 * R)
    T = TL.Town()

    def px(x, z):
        return [int(round((x - cx + R) * k)), int(round((z - cz + R) * k))]

    img = np.full((S, S, 3), 245, np.uint8)
    # 道路
    for i in range(math.floor((cx - R) / 400), math.floor((cx + R) / 400) + 1):
        for j in range(math.floor((cz - R) / 400), math.floor((cz + R) / 400) + 1):
            t = T.tile((i, j))
            if t is None:
                continue
            for name, col in (("car", (200, 200, 200)), ("alley", (212, 212, 212)), ("side", (225, 222, 215))):
                if not t.get(name):
                    continue
                for rings in TL.read_polys(TL.inflate(t[name])):
                    cv2.fillPoly(img, [np.array([px(i * 400 + p[0], j * 400 + p[1]) for p in r], np.int32) for r in rings], col)
    # 目盛り
    g0x, g0z = math.ceil((cx - R) / 50) * 50, math.ceil((cz - R) / 50) * 50
    x = g0x
    while x < cx + R:
        cv2.line(img, tuple(px(x, cz - R)), tuple(px(x, cz + R)), (228, 228, 235), 1)
        cv2.putText(img, str(int(x)), (px(x, 0)[0] + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (150, 110, 110), 1)
        x += 50
    z = g0z
    while z < cz + R:
        cv2.line(img, tuple(px(cx - R, z)), tuple(px(cx + R, z)), (228, 228, 235), 1)
        cv2.putText(img, str(int(z)), (2, px(0, z)[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (150, 110, 110), 1)
        z += 50
    # 経路（すべての形）
    routes = json.load(open(os.path.join(TL.DATA, "routes.json"), encoding="utf-8"))
    for P in routes["patterns"]:
        pts = P["pts"]
        line = [px(pts[i] / 10, pts[i + 1] / 10) for i in range(0, len(pts), 2) if abs(pts[i] / 10 - cx) < R * 1.2 and abs(pts[i + 1] / 10 - cz) < R * 1.2]
        for p, q in zip(line, line[1:]):
            if abs(p[0] - q[0]) + abs(p[1] - q[1]) < 80:
                cv2.line(img, tuple(p), tuple(q), (230, 150, 60), 2)
    # 建物
    B = T.buildings_near(cx, cz, R * 1.3)
    B.sort(key=lambda b: math.hypot(sum(p[0] for p in b[2]) / len(b[2]) - cx, sum(p[1] for p in b[2]) / len(b[2]) - cz))
    rows = []
    for n, (ty, h, W) in enumerate(B):
        pts = np.array([px(*p) for p in W], np.int32)
        col = [(120, 140, 170), (200, 200, 150), (110, 110, 190), (190, 190, 120)][ty]
        cv2.fillPoly(img, [pts], col)
        cv2.polylines(img, [pts], True, (60, 60, 60), 1)
        bx, bz = sum(p[0] for p in W) / len(W), sum(p[1] for p in W) / len(W)
        area = abs(TL.poly_area(W))
        if area > 40:
            c = px(bx, bz)
            cv2.putText(img, str(n), (c[0] - 6, c[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 3)
            cv2.putText(img, str(n), (c[0] - 6, c[1] + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)
        rows.append((n, round(bx, 1), round(bz, 1), round(area), h, ty, len(W)))
    # 停留所
    try:
        g = json.load(open(os.path.join(TL.DATA, "gtfs_umikko.json"), encoding="utf-8"))
        for line in g["stops.txt"].splitlines()[1:]:
            f = line.split(",")
            if len(f) > 4:
                sx, sz = TL.to_xz(float(f[3]), float(f[4]))
                if abs(sx - cx) < R and abs(sz - cz) < R:
                    cv2.circle(img, tuple(px(sx, sz)), 6, (40, 40, 220), 2)
    except Exception:
        pass
    cv2.drawMarker(img, tuple(px(cx, cz)), (0, 0, 255), cv2.MARKER_CROSS, 16, 1)
    cv2.imwrite(out, img)
    print("中心 x=%.1f z=%.1f（上が北・1 目盛り 50m）" % (cx, cz))
    for r in rows:
        if r[3] > 40:
            print("  #%d  x=%.1f z=%.1f  %d㎡  高さ %.1fm  種類 %d  角 %d" % r)


if __name__ == "__main__":
    main()
