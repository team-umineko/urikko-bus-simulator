# -*- coding: utf-8 -*-
"""建物 1 棟の形を調べる： python tools/bldinfo.py <x> <z>   （その点にいちばん近い建物）
辺ごとに、長さと、外向きの方位（北 0°・東 90°・南 180°・西 270°）を出す。"""
import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import townlib as TL

x, z = float(sys.argv[1]), float(sys.argv[2])
T = TL.Town()
B = T.buildings_near(x, z, 80)
B.sort(key=lambda b: 0 if TL.in_poly(b[2], x, z) else 1 + math.hypot(sum(p[0] for p in b[2]) / len(b[2]) - x, sum(p[1] for p in b[2]) / len(b[2]) - z))
ty, h, W = B[0]
A = TL.poly_area(W)
print("種類 %d・高さ %.1fm・面積 %.0f㎡・角 %d・地面の高さ %s" % (ty, h, abs(A), len(W), ", ".join("%.1f" % (T.h_at(*p) or 0) for p in W[:6])))
for i in range(len(W)):
    a, b = W[i], W[(i + 1) % len(W)]
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    nx, nz = (b[1] - a[1]) / L, -(b[0] - a[0]) / L
    if A < 0:
        nx, nz = -nx, -nz
    az = math.degrees(math.atan2(nx, -nz)) % 360
    print("  辺 %2d  (%.1f, %.1f) → (%.1f, %.1f)  長さ %5.1fm  外向き %3.0f°" % (i, a[0], a[1], b[0], b[1], L, az))
