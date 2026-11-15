# -*- coding: utf-8 -*-
"""川・池・水路のデータ（data/water.json）を作る。

基盤地図情報（元データ/地図/基盤地図情報 の zip）の
  ・水域（WA）の「河川・湖池」（縮尺 2500 の形）……川と池の水面の形
  ・水涯線（WL）の「一条河川」…………………………幅の狭い水路・小川（中心の線）
を、町のタイル（data/town）の範囲だけ読み、町の座標（x 東・z 南、m）にする。

水面の高さは、岸（形の外 2m の地面）の高さから決める：
  ・各点の、川の向こう岸までの幅 w を測り、その点から w＋4m 以内の岸の高さのいちばん低い所から、
    深さ（川は 0.9＋0.04w m、1.0〜2.2m。池は 0.7m）を引く。点の列にそってならす。海面（0m）より下にはしない。
  ・形が地図の区画の線で切れている辺（となりの形と同じ辺・海との境）は「切れ目」として、壁を作らない。

出力：
  {"R": [{"k": 0 川 / 1 池, "r": [[x, z, 水面の高さ, 切れ目 0/1, ...], 穴...]}],
   "D": [{"w": 幅, "p": [x, z, 水面の高さ, ...]}],
   "t": {"i,j": [[川・池の番号...], [水路の番号...]]}}

使い方： python tools/make_water.py
"""
import glob
import io
import json
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import townlib as TL  # noqa: E402

ROOT = os.path.join(HERE, "..")
SRC = os.path.join(ROOT, "元データ", "地図", "基盤地図情報")
OUT = os.path.join(ROOT, "data", "water.json")
DITCH_W = 1.4


def read_fgd():
    wa, wl = [], []
    for zp in sorted(glob.glob(os.path.join(SRC, "*.zip"))):
        z = zipfile.ZipFile(zp)
        for nm in ("WA", "WL"):
            fn = [i.filename for i in z.infolist() if "-%s-" % nm in i.filename]
            if not fn:
                continue
            s = z.read(fn[0]).decode("utf-8")
            for m in re.finditer(r"<%s gml:id=[^>]*>(.*?)</%s>" % (nm, nm), s, re.S):
                body = m.group(1)
                ty = re.search(r"<type>([^<]*)</type>", body)
                ty = ty.group(1) if ty else ""
                lv = re.search(r"<orgGILvl>([^<]*)</orgGILvl>", body)
                lv = lv.group(1) if lv else ""

                def ll(t):
                    R = []
                    for pl in re.findall(r"<gml:posList>(.*?)</gml:posList>", t, re.S):
                        v = pl.split()
                        R += [(float(v[i]), float(v[i + 1])) for i in range(0, len(v) - 1, 2)]
                    return R
                if nm == "WA":
                    ext = re.search(r"<gml:exterior>(.*?)</gml:exterior>", body, re.S)
                    if not ext:
                        continue
                    rings = [ll(ext.group(1))] + [ll(t) for t in re.findall(r"<gml:interior>(.*?)</gml:interior>", body, re.S)]
                    wa.append({"type": ty, "lv": lv, "rings": rings})
                elif ty == "一条河川" and lv == "2500":
                    wl.append(ll(body))
    return wa, wl


def area(r):
    s = 0.0
    for i in range(len(r)):
        j = (i + 1) % len(r)
        s += r[i][0] * r[j][1] - r[j][0] * r[i][1]
    return s / 2


def in_rings(rings, x, z):
    ins = False
    for R in rings:
        for i in range(len(R)):
            a, b = R[i], R[i - 1]
            if (a[1] > z) != (b[1] > z) and x < (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]:
                ins = not ins
    return ins


def main():
    T = TL.Town()
    keys = set(T.keys())
    wa, wl = read_fgd()
    print("水域", len(wa), "一条河川", len(wl))
    # となりの形と同じ辺（地図の区画の線で切れた所・海との境）を数える
    ek = {}

    def ekey(p, q):
        a, b = (round(p[0], 7), round(p[1], 7)), (round(q[0], 7), round(q[1], 7))
        return (a, b) if a < b else (b, a)
    for f in wa:
        if f["lv"] == "25000":
            continue
        for R in f["rings"]:
            for i in range(len(R) - 1):
                k = ekey(R[i], R[i + 1])
                ek[k] = ek.get(k, 0) + 1
    # 川・池
    R_out, t_out = [], {}
    for f in wa:
        if f["type"] != "河川・湖池" or f["lv"] != "2500":
            continue
        rings_ll = [R[:-1] if len(R) > 1 and R[0] == R[-1] else R for R in f["rings"]]
        rings = [[TL.to_xz(a, b) for a, b in R] for R in rings_ll]
        xs = [p[0] for p in rings[0]]
        zs = [p[1] for p in rings[0]]
        tk = [(i, j) for i in range(math.floor(min(xs) / 400), math.floor(max(xs) / 400) + 1)
              for j in range(math.floor(min(zs) / 400), math.floor(max(zs) / 400) + 1) if (i, j) in keys]
        if not tk:
            continue
        A = abs(area(rings[0])) - sum(abs(area(r)) for r in rings[1:])
        P = sum(math.hypot(r[(i + 1) % len(r)][0] - r[i][0], r[(i + 1) % len(r)][1] - r[i][1]) for r in rings for i in range(len(r)))
        if A < 6:
            continue
        kind = 1 if P * P / (4 * math.pi * A) < 3.2 else 0          # 丸みのある形は池
        # 各点：切れ目か・岸の高さ・向こう岸までの幅
        out_rings = []
        allpts = []
        for ri, (R, Rl) in enumerate(zip(rings, rings_ll)):
            n = len(R)
            pts = []
            for i in range(n):
                p, q = R[i], R[(i + 1) % n]
                cut = ek.get(ekey(Rl[i], Rl[(i + 1) % n]), 0) >= 2
                pts.append({"x": p[0], "z": p[1], "cut": cut})
            # 水のある側の向き（左の法線の先が形の中なら、左が水）
            best = max(range(n), key=lambda i: math.hypot(R[(i + 1) % n][0] - R[i][0], R[(i + 1) % n][1] - R[i][1]))
            a, b = R[best], R[(best + 1) % n]
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
            lx, lz = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
            sgn = 1 if in_rings(rings, (a[0] + b[0]) / 2 + lx * 0.2, (a[1] + b[1]) / 2 + lz * 0.2) else -1
            for i in range(n):
                p0, p1, p2 = R[i - 1], R[i], R[(i + 1) % n]
                tx, tz = p2[0] - p0[0], p2[1] - p0[1]
                L = math.hypot(tx, tz) or 1
                wx, wz = -tz / L * sgn, tx / L * sgn            # 水の側
                h = T.h_at(p1[0] - wx * 2.0, p1[1] - wz * 2.0)
                pts[i]["hb"] = h
                # 向こう岸までの幅：水の側へ 0.5m ごとに進み、形の外に出るまで（60m まで）
                w = 60.0
                for k in range(1, 121):
                    if not in_rings(rings, p1[0] + wx * k * 0.5, p1[1] + wz * k * 0.5):
                        w = k * 0.5
                        break
                pts[i]["w"] = w
            out_rings.append(pts)
            allpts += pts
        # 水面の高さ
        hbs = [p for p in allpts if p["hb"] is not None]
        if not hbs:
            continue
        for p in allpts:
            R_ = p["w"] + 4
            near = [q["hb"] for q in hbs if abs(q["x"] - p["x"]) < R_ and abs(q["z"] - p["z"]) < R_ and math.hypot(q["x"] - p["x"], q["z"] - p["z"]) < R_]
            lo = min(near) if near else min(q["hb"] for q in hbs)
            depth = 0.7 if kind == 1 else min(2.2, max(1.0, 0.9 + 0.04 * p["w"]))
            p["wl"] = lo - depth
        if kind == 1:
            lv = min(p["wl"] for p in allpts)
            for p in allpts:
                p["wl"] = lv
        for pts in out_rings:
            n = len(pts)
            sm = []
            for i in range(n):
                s = [pts[(i + k) % n]["wl"] for k in range(-3, 4)]
                sm.append(sum(s) / len(s))
            for i in range(n):
                pts[i]["wl"] = max(0.05, sm[i])
        idx = len(R_out)
        R_out.append({"k": kind, "r": [[v for p in pts for v in (round(p["x"], 2), round(p["z"], 2), round(p["wl"], 2), 1 if p["cut"] else 0)] for pts in out_rings]})
        for k in tk:
            t_out.setdefault("%d,%d" % k, [[], []])[0].append(idx)
    print("川・池", len(R_out), "（池", sum(1 for r in R_out if r["k"] == 1), "）")
    # 水路（一条河川）：川・池の中を通る所は除く。0.3m より近い点は間引く
    D_out = []
    for line in wl:
        P = [TL.to_xz(a, b) for a, b in line]
        Q = [P[0]]
        for p in P[1:]:
            if math.hypot(p[0] - Q[-1][0], p[1] - Q[-1][1]) >= 0.3:
                Q.append(p)
        if len(Q) < 2:
            continue
        xs = [p[0] for p in Q]
        zs = [p[1] for p in Q]
        tk = [(i, j) for i in range(math.floor(min(xs) / 400), math.floor(max(xs) / 400) + 1)
              for j in range(math.floor(min(zs) / 400), math.floor(max(zs) / 400) + 1) if (i, j) in keys]
        if not tk:
            continue
        flat = []
        for p in Q:
            h = T.h_at(p[0], p[1])
            if h is None:
                h = 0.5
            flat += [round(p[0], 2), round(p[1], 2), round(max(0.05, h - 0.75), 2)]
        idx = len(D_out)
        D_out.append({"w": DITCH_W, "p": flat})
        for k in tk:
            t_out.setdefault("%d,%d" % k, [[], []])[1].append(idx)
    print("水路", len(D_out))
    json.dump({"src": "基盤地図情報（国土地理院）水域・水涯線", "R": R_out, "D": D_out, "t": t_out},
              io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("書き出し", OUT, os.path.getsize(OUT) // 1024, "KB")


if __name__ == "__main__":
    main()
