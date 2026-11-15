# -*- coding: utf-8 -*-
"""経路ぞいの家の 1 軒ごとの屋根の色と形を、国土地理院の航空写真（シームレス空中写真）から読み取る。

1. 町のタイル（400m）ごとに、航空写真を 0.5m のます目に並べなおす。
2. 建物の形（基盤地図情報）と航空写真は、2〜5m ずれていることがある（写真の傾き・位置合わせの差）。
   タイルの中の建物全部について、屋根の内側とまわり（0.5〜1.5m 外）の明るさの差がいちばん大きくなるずらし方を探し（±6m）、
   そのずれを直して読む。
3. 建物ごとに：
   色：屋根の内側（ふちから 1m 内側）の画素の、明るさの中ほど（30〜70%）の平均
   形：いちばん小さく囲む四角形で、屋根の面ごとの明るさのちがいから
       g＝切妻（棟は長い辺に平行）・s＝切妻（棟は短い辺に平行）・h＝寄棟・f＝平ら・""＝はっきりしない
data/houses.json：{"src", "shift": {"i,j": [dx, dz]}, "t": {"i,j": {"番号": "rrggbb[:形]"}}}

使い方： python tools/house_colors.py
出典：国土地理院 シームレス空中写真（地理院タイル）、基盤地図情報（建物）
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
import aerial as AE  # noqa: E402

ROOT = os.path.join(HERE, "..")
NEAR = 90.0
TILE = 400
RES = 0.5                 # ます目の大きさ（m）
N = int(TILE / RES)
SH = 12                   # ずれを探す範囲（ます目。±6m）


def route_points():
    R = json.load(io.open(os.path.join(ROOT, "data", "routes.json"), encoding="utf-8"))
    rp = []
    for P in R["patterns"]:
        a = P["pts"]
        xy = [(a[i] / 10, a[i + 1] / 10) for i in range(0, len(a), 2)]
        for i in range(len(xy) - 1):
            (ax, az), (bx, bz) = xy[i], xy[i + 1]
            n = max(1, int(math.hypot(bx - ax, bz - az) // 10))
            for k in range(n):
                rp.append((ax + (bx - ax) * k / n, az + (bz - az) * k / n))
    return rp


def tile_image(key):
    """町のタイル key の航空写真（N×N×3、北が上、x 東・z 南）"""
    ox, oz = key[0] * TILE, key[1] * TILE
    lat0, lon0 = TL.to_ll(ox, oz)
    lat1, lon1 = TL.to_ll(ox + TILE, oz + TILE)
    xs = ox + (np.arange(N) + 0.5) * RES
    zs = oz + (np.arange(N) + 0.5) * RES
    lon = lon0 + (xs - ox) / TILE * (lon1 - lon0)
    lat = lat0 + (zs - oz) / TILE * (lat1 - lat0)
    n = 2 ** AE.Z
    tx = (lon + 180) / 360 * n
    ty = (1 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2 * n
    tx0, tx1, ty0, ty1 = int(tx.min()), int(tx.max()), int(ty.min()), int(ty.max())
    mos = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    for i in range(tx0, tx1 + 1):
        for j in range(ty0, ty1 + 1):
            mos[(j - ty0) * 256:(j - ty0 + 1) * 256, (i - tx0) * 256:(i - tx0 + 1) * 256] = np.asarray(AE.get(i, j).convert("RGB"))
    px = np.clip(((tx - tx0) * 256).astype(int), 0, mos.shape[1] - 1)
    py = np.clip(((ty - ty0) * 256).astype(int), 0, mos.shape[0] - 1)
    return mos[py[:, None], px[None, :]]


def main():
    rp = route_points()
    G = {}
    for p in rp:
        G.setdefault((int(p[0] // 50), int(p[1] // 50)), []).append(p)

    def near(x, z):
        i0, j0 = int(x // 50), int(z // 50)
        for i in range(i0 - 2, i0 + 3):
            for j in range(j0 - 2, j0 + 3):
                for p in G.get((i, j), ()):
                    if (p[0] - x) ** 2 + (p[1] - z) ** 2 < NEAR * NEAR:
                        return True
        return False

    T = TL.Town()
    keys = sorted({(int(math.floor(p[0] / TILE)), int(math.floor(p[1] / TILE))) for p in rp})
    keys = sorted({(i + di, j + dj) for (i, j) in keys for di in (-1, 0, 1) for dj in (-1, 0, 1)})
    work = []
    for key in keys:
        t = T.tile(key)
        if t is None:
            continue
        B = []
        for q, (ty, h, P) in enumerate(TL.read_buildings(t)):
            if abs(TL.poly_area(P)) < 12:
                continue
            cx, cz = key[0] * TILE + sum(p[0] for p in P) / len(P), key[1] * TILE + sum(p[1] for p in P) / len(P)
            if near(cx, cz):
                B.append((q, ty, P))
        if B:
            work.append((key, B))
    print("タイル", len(work), "建物", sum(len(b) for _, b in work))
    out, shifts, stat = {}, {}, {}
    for key, B in work:
        img = tile_image(key)
        Lum = (0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]).astype(np.float32)
        # 建物の形のます目（内側・まわりの輪）から、写真とのずれを探す
        mask = np.zeros((N, N), np.uint8)
        polys = [np.array([[p[0] / RES, p[1] / RES] for p in P], np.int32) for q, ty, P in B]
        cv2.fillPoly(mask, polys, 1)
        inner = cv2.erode(mask, np.ones((3, 3), np.uint8)).astype(bool)
        ring = (cv2.dilate(mask, np.ones((7, 7), np.uint8)) - cv2.dilate(mask, np.ones((3, 3), np.uint8))).astype(bool)
        best, bs = (0, 0), -1.0
        Lp = np.pad(Lum, SH, mode="edge")
        if inner.sum() > 200 and ring.sum() > 200:
            for dy in range(-SH, SH + 1):
                for dx in range(-SH, SH + 1):
                    S = Lp[SH + dy:SH + dy + N, SH + dx:SH + dx + N]
                    sc = abs(float(S[inner].mean()) - float(S[ring].mean()))
                    if sc > bs:
                        bs, best = sc, (dx, dy)
        dx, dy = best
        shifts["%d,%d" % key] = [dx * RES, dy * RES]
        imgS = np.pad(img, ((SH, SH), (SH, SH), (0, 0)), mode="edge")[SH + dy:SH + dy + N, SH + dx:SH + dx + N]
        LS = Lp[SH + dy:SH + dy + N, SH + dx:SH + dx + N]
        LSp = np.pad(LS, 4, mode="edge")
        imgSp = np.pad(imgS, ((4, 4), (4, 4), (0, 0)), mode="edge")
        for (q, ty, P), pts in zip(B, polys):
            x0, y0 = max(0, int(pts[:, 0].min()) - 4), max(0, int(pts[:, 1].min()) - 4)
            x1, y1 = min(N, int(pts[:, 0].max()) + 5), min(N, int(pts[:, 1].max()) + 5)
            if x1 - x0 < 3 or y1 - y0 < 3:
                continue
            m = np.zeros((y1 - y0, x1 - x0), np.uint8)
            cv2.fillPoly(m, [pts - np.array([x0, y0], np.int32)], 1)
            # 1 軒ごとのずれ（±1.5m）：屋根の内側とまわりの明るさの差がいちばん大きい所
            mi = cv2.erode(m, np.ones((3, 3), np.uint8)).astype(bool)
            mr = (cv2.dilate(m, np.ones((5, 5), np.uint8)) - m).astype(bool)
            bx, by, bsc = 0, 0, -1.0
            if mi.sum() >= 8 and mr.sum() >= 8:
                for ddy in range(-3, 4):
                    for ddx in range(-3, 4):
                        Sb = LSp[4 + y0 + ddy:4 + y1 + ddy, 4 + x0 + ddx:4 + x1 + ddx]
                        sc = abs(float(Sb[mi].mean()) - float(Sb[mr].mean())) - 0.3 * (abs(ddx) + abs(ddy))
                        if sc > bsc:
                            bsc, bx, by = sc, ddx, ddy
            LSb = LSp[4 + y0 + by:4 + y1 + by, 4 + x0 + bx:4 + x1 + bx]
            imgB = imgSp[4 + y0 + by:4 + y1 + by, 4 + x0 + bx:4 + x1 + bx]
            m1 = cv2.erode(m, np.ones((3, 3), np.uint8)).astype(bool)          # ふちから 0.5m 内側（形を見る）
            m2 = cv2.erode(m, np.ones((5, 5), np.uint8)).astype(bool)          # ふちから 1m 内側（色を見る）
            cols = imgB[m2 if m2.sum() >= 6 else m1].astype(np.float32)
            if len(cols) < 6:
                continue
            lum = cols @ np.array([0.299, 0.587, 0.114], np.float32)
            o = np.argsort(lum)
            mid = cols[o[int(len(o) * 0.3):max(int(len(o) * 0.7), int(len(o) * 0.3) + 1)]].mean(axis=0)
            yy, xx = np.nonzero(m1)
            tp = roof_type(P, (xx + x0 + 0.5) * RES, (yy + y0 + 0.5) * RES, LSb[m1])
            stat[tp] = stat.get(tp, 0) + 1
            out.setdefault("%d,%d" % key, {})[str(q)] = "%02x%02x%02x" % tuple(int(v) for v in mid) + (":" + tp if tp else "")
        print(key, "ずれ", shifts["%d,%d" % key], "建物", len(B))
    print("屋根の形", stat)
    io.open(os.path.join(ROOT, "data", "houses.json"), "w", encoding="utf-8").write(json.dumps(
        {"src": "屋根の色と形：国土地理院 シームレス空中写真（地理院タイル）から、建物ごとに読み取り（建物の形とのずれはタイルごとに直した）。"
                "形 g＝切妻（棟は長い辺に平行）・s＝切妻（棟は短い辺に平行）・h＝寄棟・f＝平ら",
         "shift": shifts, "t": out}, ensure_ascii=False, separators=(",", ":")))
    print("読んだ建物", sum(len(v) for v in out.values()))


def roof_type(P, xs, zs, ys):
    """屋根の形を、屋根の面ごとの明るさのちがいから見分ける（四角に近い 25〜400㎡ の建物だけ）。P・xs・zs はタイルの中の座標。
      S±：長い辺の側の面、E±：短い辺の側の三角（辺から 45° の線で分ける）、M±：端の三角を除いた真ん中の帯の左右
      ・切妻（棟が長い辺に平行）：S+ と S- がちがい、端の三角も上下（棟の両側）でちがう
      ・寄棟：S+ と S- はちがうが、端の三角の上下はほぼ同じ（1 つの面）。日の向きと棟が直角なら、端の三角どうしだけがちがう
      ・切妻（棟が短い辺に平行）：真ん中の帯の左右がちがう
      ・平ら：どの分け方でもちがいが小さく、ばらつきも小さい"""
    if len(ys) < 40:
        return ""
    area = abs(TL.poly_area(P))
    if area < 25 or area > 400:
        return ""
    best = None
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1:
            continue
        ux, uz = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        us = [p[0] * ux + p[1] * uz for p in P]
        vs = [-p[0] * uz + p[1] * ux for p in P]
        ar = (max(us) - min(us)) * (max(vs) - min(vs))
        if best is None or ar < best[0]:
            best = (ar, ux, uz, (max(us) + min(us)) / 2, (max(vs) + min(vs)) / 2, (max(us) - min(us)) / 2, (max(vs) - min(vs)) / 2)
    ar, ux, uz, cu, cv, A, B = best
    if area / ar < 0.85:
        return ""
    if B > A:
        ux, uz, cu, cv, A, B = -uz, ux, cv, -cu, B, A
    u = xs * ux + zs * uz - cu
    v = -xs * uz + zs * ux - cv
    endf = (A - np.abs(u)) < (B - np.abs(v))
    mid = (~endf) & (np.abs(u) < (A - B) * 0.9)

    def m(sel):
        return float(ys[sel].mean()) if sel.sum() >= 3 else None
    sp, sm = m(~endf & (v > 0)), m(~endf & (v <= 0))
    hp, hm = m(u > 0), m(u <= 0)
    if None in (sp, sm, hp, hm):
        return ""
    sd = float(ys.std())
    dS, dH = abs(sp - sm), abs(hp - hm)
    if dS < 6 and dH < 6 and sd < 9:
        return "f"
    if dS < 10:
        ep, em, mp, mm = m(endf & (u > 0)), m(endf & (u <= 0)), m(mid & (u > 0)), m(mid & (u <= 0))
        if None in (ep, em):
            return ""
        if mp is not None and mm is not None and abs(mp - mm) > 14 and dH > 12:
            return "s"
        if abs(ep - em) > 15 and (mp is None or mm is None or abs(mp - mm) < 5):
            return "h"
        return ""
    ed = []
    for s_ in (1, -1):
        sel = endf & (u * s_ > 0)
        t, b_ = m(sel & (v > 0)), m(sel & (v <= 0))
        if t is not None and b_ is not None:
            ed.append(abs(t - b_))
    if not ed:
        return ""
    r = (sum(ed) / len(ed)) / dS
    if r < 0.25:
        return "h"
    if r > 0.8:
        return "g"
    return ""


if __name__ == "__main__":
    main()
