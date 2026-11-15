# -*- coding: utf-8 -*-
"""田・畑・果樹園・温室のデータ（data/fields.json）を作る。

もとにするもの
  ・国土地理院ベクトルタイルの植生の記号（田・畑・果樹園・針葉樹林…）  → tools/fetch_gsi_symbols.py で集めた symbols.json
  ・OpenStreetMap の農地（landuse=farmland）と温室（landuse=greenhouse_horticulture）の区画  → 元データ/地図/OSM/export.json
  ・町のデータ（data/town）：建物・道路・森・標高

考え方
  地形図の記号は「このあたりは田」「このあたりは果樹園」を表す。そこで 2m ごとのマスについて、
  いちばん近い記号が田・畑・果樹園で、建物・道路・海でなく、家が建てこんでいない所を、その種類の農地とする。
  もとの町のデータでは果樹園の 7 割・畑の 4 割が「森」になっていたので、農地の記号のすぐ近く（45m 以内）は森より農地を優先する。
  OSM の農地の区画の中は、記号が遠くても農地にする（種類は近くの記号から。無ければ畑）。
  畝・稲株の向きは、100m ごとに、いちばん近い道路の向きに合わせる（田畑は道に沿って区切られていることが多い）。

出力（data/fields.json）
  { "res": 2, "n": 200, "t": { "i,j": PNG（base64。200×200、R＝種類 0 なし・85 田・170 畑・255 果樹園、G＝畝の向き 0〜255＝0〜180°、B＝区画ごとの乱数） },
    "gh": { "i,j": [[中心 x, 中心 z, 長さ, 幅, 向き(rad)], ...] }, "src": 出典 }

使い方： python tools/make_fields.py [--debug 画像を書き出すフォルダ]
"""
import base64
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
SYM = os.path.join(ROOT, "元データ", "地図", "地理院地図Vector", "symbols.json")
OSM_CANDIDATES = [os.path.join(ROOT, "元データ", "地図", "OSM", "export.json"),
                  os.path.join(os.path.expanduser("~"), "Documents", "南知多素材", "売りっ子バスシミュレーター　参考文献", "export.json")]
OUT = os.path.join(ROOT, "data", "fields.json")
RES = 2.0                 # マスの大きさ（m）
N = int(TL.TILE / RES)    # タイル 1 枚のマスの数（200）
FARM = {6311: 1, 6312: 2, 6314: 3, 6313: 2}       # 田・畑・果樹園（茶畑は畑として扱う）
R_SYMBOL = 85.0           # 記号からこの距離までを、その記号の農地とする
R_OVER_FOREST = 45.0      # 記号からこの距離までは、町のデータが森でも農地にする
R_KEEP_NEAR_HOUSES = 22.0 # 家が建てこんだ所でも、記号からこの距離までは農地にする


def find_osm():
    for p in OSM_CANDIDATES:
        if os.path.exists(p):
            return p
    # 元データ/地図/OSM の中の json を探す
    d = os.path.join(ROOT, "元データ", "地図", "OSM")
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith(".json"):
                return os.path.join(d, f)
    return None


def main():
    debug = sys.argv[sys.argv.index("--debug") + 1] if "--debug" in sys.argv else None
    T = TL.Town()
    keys = T.keys()
    i0, i1 = min(k[0] for k in keys), max(k[0] for k in keys)
    j0, j1 = min(k[1] for k in keys), max(k[1] for k in keys)
    W, H = (i1 - i0 + 1) * N, (j1 - j0 + 1) * N
    X0, Z0 = i0 * TL.TILE, j0 * TL.TILE
    print("範囲 タイル i %d〜%d・j %d〜%d、%d×%d マス" % (i0, i1, j0, j1, W, H))

    def px(x, z):
        return (x - X0) / RES, (z - Z0) / RES

    have = np.zeros((H, W), np.uint8)       # 町のデータがある所
    bld = np.zeros((H, W), np.uint8)        # 建物
    road = np.zeros((H, W), np.uint8)       # 道路（車道・歩道・路地）
    forest = np.zeros((H, W), np.uint8)
    low = np.zeros((H, W), np.uint8)        # 海・水ぎわ（標高 0.5m 未満）
    steep = np.zeros((H, W), np.uint8)      # 急な斜面
    centers = []                            # 建物の中心（家が建てこんでいるかを見る）
    edges = []                              # 道路の縁の線分（中点 x, z, 向き, 長さ）
    for k in keys:
        t = T.tile(k)
        ox, oz = k[0] * TL.TILE, k[1] * TL.TILE
        c0, r0 = (k[0] - i0) * N, (k[1] - j0) * N
        have[r0:r0 + N, c0:c0 + N] = 1
        Hh = np.array(T.heights(k), np.float32).reshape(TL.GN, TL.GN)
        up = cv2.resize(Hh, (N + 1, N + 1), interpolation=cv2.INTER_LINEAR)[:N, :N]
        low[r0:r0 + N, c0:c0 + N] = (up < 0.5).astype(np.uint8)
        gy, gx = np.gradient(Hh, TL.GS)
        sl = cv2.resize(np.hypot(gx, gy).astype(np.float32), (N + 1, N + 1), interpolation=cv2.INTER_LINEAR)[:N, :N]
        steep[r0:r0 + N, c0:c0 + N] = (sl > 0.55).astype(np.uint8)
        F = np.array(TL.read_forest(t), np.uint8)
        forest[r0:r0 + N, c0:c0 + N] = cv2.resize(F, (N, N), interpolation=cv2.INTER_NEAREST)
        for ty, h, P in TL.read_buildings(t):
            pts = np.array([px(ox + p[0], oz + p[1]) for p in P], np.float32)
            cv2.fillPoly(bld, [np.round(pts).astype(np.int32)], 1)
            if ty in (0, 2):
                centers.append((float(pts[:, 0].mean()), float(pts[:, 1].mean())))
        for name in ("car", "side", "alley"):
            if not t.get(name):
                continue
            for rings in TL.read_polys(TL.inflate(t[name])):
                pts = [np.round(np.array([px(ox + p[0], oz + p[1]) for p in r], np.float32)).astype(np.int32) for r in rings]
                cv2.fillPoly(road, pts, 1)
                if name == "side":
                    continue
                for r in rings:
                    for a, b in zip(r, r[1:] + r[:1]):
                        L = math.hypot(b[0] - a[0], b[1] - a[1])
                        if L >= 6:
                            edges.append((ox + (a[0] + b[0]) / 2, oz + (a[1] + b[1]) / 2, math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi, L))
    edges = np.array(edges, np.float32)
    print("建物 %d 棟・道路の縁 %d 本" % (len(centers), len(edges)))

    # 記号までの距離（種類ごと）
    sym = json.load(open(SYM, encoding="utf-8"))
    by = {}
    for lat, lon, c in sym["pts"]:
        x, z = TL.to_xz(lat, lon)
        u, v = px(x, z)
        if -200 <= u < W + 200 and -200 <= v < H + 200:
            by.setdefault(FARM.get(c, 0), []).append((u, v))
    dist = {}
    for cls, P in by.items():
        m = np.full((H, W), 255, np.uint8)
        for u, v in P:
            if 0 <= u < W and 0 <= v < H:
                m[int(v), int(u)] = 0
        dist[cls] = cv2.distanceTransform(m, cv2.DIST_L2, 5) * RES
        print("記号 種類 %d：%d 個" % (cls, len(P)))
    INF = np.full((H, W), 1e9, np.float32)
    d_farm = np.minimum.reduce([dist.get(c, INF) for c in (1, 2, 3)])
    d_other = dist.get(0, INF)
    cls_near = np.argmin(np.stack([dist.get(c, INF) for c in (1, 2, 3)]), axis=0).astype(np.uint8) + 1

    # 家が建てこんでいる所：半径 36m に建物の中心が 4 つ以上
    cm = np.zeros((H, W), np.float32)
    for u, v in centers:
        if 0 <= u < W and 0 <= v < H:
            cm[int(v), int(u)] += 1
    r = int(36 / RES)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)).astype(np.float32)
    dense = cv2.filter2D(cm, -1, kern, borderType=cv2.BORDER_CONSTANT) >= 4

    # OSM の農地・温室
    osm = find_osm()
    osm_farm = np.zeros((H, W), np.uint8)
    gh_mask = np.zeros((H, W), np.uint8)
    greenhouses = []
    if osm:
        d = json.load(open(osm, encoding="utf-8"))
        nodes = {e["id"]: (e["lat"], e["lon"]) for e in d["elements"] if e["type"] == "node"}
        for e in d["elements"]:
            if e["type"] != "way":
                continue
            lu = e.get("tags", {}).get("landuse")
            if lu not in ("farmland", "greenhouse_horticulture", "orchard"):
                continue
            P = [TL.to_xz(*nodes[n]) for n in e["nodes"] if n in nodes]
            if len(P) < 4:
                continue
            pts = np.round(np.array([px(*p) for p in P], np.float32)).astype(np.int32)
            if lu == "greenhouse_horticulture":
                (cx, cz), (w, h), ang = cv2.minAreaRect(np.array(P, np.float32))
                if w < h:
                    w, h, ang = h, w, ang + 90
                if 6 <= w <= 140 and 3 <= h <= 80:
                    greenhouses.append((cx, cz, w, h, math.radians(ang) % math.pi))
                    cv2.fillPoly(gh_mask, [pts], 1)
            else:
                cv2.fillPoly(osm_farm, [pts], 1)
        print("OSM：農地 %.0f ha・温室 %d 棟（%s）" % (osm_farm.sum() * RES * RES / 1e4, len(greenhouses), os.path.basename(os.path.dirname(osm))))
    else:
        print("OSM のデータが見つからない（記号だけで作る）")

    # 農地になれる所：建物（まわり 2m）・道路（まわり 1m）・海・急な斜面・温室を除く
    k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    block = cv2.dilate(bld, k5) | cv2.dilate(road, k3) | low | cv2.dilate(gh_mask, k5)
    ok = (have == 1) & (block == 0)
    by_symbol = (d_farm <= R_SYMBOL) & (d_farm <= d_other)
    # 森の中の農地（果樹園に多い）：記号からの距離の限りを場所ごとに変える（まん丸にならないように。120m ごとのなだらかな乱数）
    rs = np.random.RandomState(11)
    wob = cv2.resize(rs.rand(H // 60 + 2, W // 60 + 2).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    wob2 = cv2.resize(rs.rand(H // 14 + 2, W // 14 + 2).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    r_over = R_OVER_FOREST - 10 + 34 * wob + 10 * wob2
    by_symbol &= (forest == 0) | (d_farm <= r_over)
    by_symbol &= ~dense | (d_farm <= R_KEEP_NEAR_HOUSES)
    by_symbol &= (steep == 0) | (cls_near == 3)            # 急な斜面は果樹園だけ
    by_osm = (osm_farm == 1) & (forest == 0) & ~dense & (steep == 0)
    farm = ok & (by_symbol | by_osm)
    # こまかい点を消し、小さな穴をうめる
    f8 = farm.astype(np.uint8)
    # となり合う農地のあいだのせまいすき間（28m まで）をうめる（道路・建物などは除いたまま）
    k15 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    f8 = cv2.morphologyEx(f8, cv2.MORPH_CLOSE, k15) & ok.astype(np.uint8) & ((dense == 0) | (d_farm <= R_KEEP_NEAR_HOUSES)).astype(np.uint8)
    f8 = cv2.morphologyEx(f8, cv2.MORPH_OPEN, k5)
    n, lab, st, _ = cv2.connectedComponentsWithStats(f8, connectivity=4)
    small = np.isin(lab, np.nonzero(st[:, cv2.CC_STAT_AREA] * RES * RES < 300)[0])
    f8[small] = 0
    cls = np.where(f8 == 1, cls_near, 0).astype(np.uint8)
    cls[(f8 == 1) & (d_farm > 400)] = 2                      # 記号がずっと遠い OSM の農地は畑
    # 種類の境目をなめらかに（3 マスの多数決）
    for _ in range(2):
        votes = np.stack([cv2.blur((cls == c).astype(np.float32), (7, 7)) for c in (1, 2, 3)])
        cls = np.where(cls > 0, np.argmax(votes, axis=0).astype(np.uint8) + 1, 0).astype(np.uint8)
    for c, name in ((1, "田"), (2, "畑"), (3, "果樹園")):
        print("%s：%.0f ha" % (name, (cls == c).sum() * RES * RES / 1e4))

    # 畝の向き：100m ごとに、いちばん近い道路の縁の向き（150m 以内に無ければ、となりから）。区画ごとの乱数も同じ区切りで
    B = int(100 / RES)
    bw, bh = W // B + 1, H // B + 1
    ang = np.zeros((bh, bw), np.float32)
    rnd = np.random.RandomState(7).randint(0, 256, (bh, bw)).astype(np.uint8)
    if len(edges):
        ex, ez, ea, el = edges[:, 0], edges[:, 1], edges[:, 2], edges[:, 3]
        for bj in range(bh):
            zc = Z0 + (bj + 0.5) * 100
            near = np.abs(ez - zc) < 200
            if not near.any():
                continue
            x_, z_, a_, l_ = ex[near], ez[near], ea[near], el[near]
            for bi in range(bw):
                xc = X0 + (bi + 0.5) * 100
                dd = np.hypot(x_ - xc, z_ - zc) - np.minimum(l_, 40) * 0.5      # 長い縁を少し優先
                k = int(np.argmin(dd))
                ang[bj, bi] = a_[k] if dd[k] < 150 else -1
    ang_full = cv2.resize(ang, (bw * B, bh * B), interpolation=cv2.INTER_NEAREST)[:H, :W]
    rnd_full = cv2.resize(rnd, (bw * B, bh * B), interpolation=cv2.INTER_NEAREST)[:H, :W]
    ang_full = np.where(ang_full < 0, 0.6, ang_full)
    G = np.clip(np.round(ang_full / math.pi * 255), 0, 255).astype(np.uint8)

    out = {"res": RES, "n": N, "t": {}, "gh": {},
           "src": "国土地理院ベクトルタイル（植生の記号）と OpenStreetMap（農地・温室の区画）、基盤地図情報（建物・道路）から作成"}
    total = 0
    for k in keys:
        c0, r0 = (k[0] - i0) * N, (k[1] - j0) * N
        c = cls[r0:r0 + N, c0:c0 + N]
        if not c.any():
            continue
        img = np.dstack([rnd_full[r0:r0 + N, c0:c0 + N], G[r0:r0 + N, c0:c0 + N], c * 85])   # OpenCV は B・G・R の順
        img[c == 0] = 0
        ok_, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        out["t"]["%d,%d" % k] = base64.b64encode(buf.tobytes()).decode("ascii")
        total += len(buf)
    keyset = set(keys)
    for cx, cz, w, h, a in greenhouses:
        k = (int(cx // TL.TILE), int(cz // TL.TILE))
        if k in keyset:
            out["gh"].setdefault("%d,%d" % k, []).append([round(cx, 1), round(cz, 1), round(w, 1), round(h, 1), round(a, 3)])
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("書き出し：タイル %d 枚（画像 計 %.0f KB）・温室 %d 棟 → %s（%.0f KB）" % (len(out["t"]), total / 1024, sum(len(v) for v in out["gh"].values()), os.path.relpath(OUT, ROOT), os.path.getsize(OUT) / 1024))

    if debug:
        os.makedirs(debug, exist_ok=True)
        col = np.zeros((H, W, 3), np.uint8)
        col[:] = (235, 232, 226)
        col[low == 1] = (232, 213, 183)
        col[forest == 1] = (150, 190, 150)
        col[cls == 1] = (120, 200, 235)      # 田：黄
        col[cls == 2] = (90, 140, 200)       # 畑：茶
        col[cls == 3] = (60, 150, 255)       # 果樹園：橙
        col[road == 1] = (120, 120, 120)
        col[bld == 1] = (70, 70, 90)
        col[gh_mask == 1] = (255, 255, 255)
        col[have == 0] = (200, 200, 200)
        cv2.imwrite(os.path.join(debug, "fields_all.png"), cv2.resize(col, (W // 3, H // 3), interpolation=cv2.INTER_AREA))
        np.save(os.path.join(debug, "fields_cls.npy"), cls)
        json.dump({"X0": X0, "Z0": Z0, "W": W, "H": H, "res": RES}, open(os.path.join(debug, "fields_meta.json"), "w"))
        cv2.imwrite(os.path.join(debug, "fields_full.png"), col)


if __name__ == "__main__":
    main()
