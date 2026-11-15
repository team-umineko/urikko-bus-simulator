# -*- coding: utf-8 -*-
"""師崎港の南の羽豆岬（はずみさき）の山と森を、町のデータ（data/town）に入れる。

もとの町のデータでは、岬の先（師崎港の南）が標高 0.3m の平地になっていて、森の印も無かった。
実際は、港の駐車場の南西すぐに擁壁があり、その上は高さ 20m 以上の森の山（羽豆神社・展望台がある）。

  標高：国土地理院の基盤地図 5m メッシュ（DEM5A、標高タイル dem5a_png）を使う。
        港の平地（DEM5A で約 2.6m）より高い分だけを、もとの標高に足す（平地・道路はもとのまま）。
        車道・歩道（町のデータ）から 2.5m 以内は足さず（山の上の小道＝路地は、地面に沿って描かれるので守らない）、2.5〜5.5m で少しずつ足す（道路の面とバスの高さを変えないため）。
        山ぞいの道（擁壁のある所）では、道路の山側の縁から 6.5m までは足さない。擁壁の模型（MODELS.moroSouth）は、
        縁から 2m の所に正面があり、奥行き 6.5m の段になっていて、地面の格子（4m）で坂が始まる所を段の中にかくす。
        DEM5A に値の無い所（岬の南西の森の中）は、近くの値から補い、海岸に近いほど低くする。
  森：  地理院の航空写真で緑の所と、持ち上げて 3m 以上高くなった所に森の印を付ける（道路・擁壁の前・建物の中は除く）。
  地面の色：森の所を、ほかの森と同じ色（84,104,66）に塗る。
  港の陸地：海ぞいの大きな駐車場（観光バスの止まる所）の北半分が、もとのデータでは海になっていたので、陸（0.3m）にする。

何度実行しても同じ結果になるように、はじめて実行したときの町のデータを 元データ/地図/標高/ に写しておき、いつもそこから作る。

出典：国土地理院（標高タイル・シームレス空中写真）。道路の線は OpenStreetMap（© OpenStreetMap contributors）。
使い方： python tools/fix_cape.py [--preview 出力.png]   （--preview のときはデータを書きかえない）
"""
import base64
import io
import json
import math
import os
import struct
import sys
import urllib.request
import zlib

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import townlib as TL  # noqa: E402

ROOT = os.path.join(HERE, "..")
CACHE_DEM = os.path.join(ROOT, "元データ", "地図", "標高")
CACHE_AIR = os.path.join(ROOT, "元データ", "地図", "地理院航空写真")
CHUNK = os.path.join(ROOT, "data", "town", "c_2_2.json")
ORIG = os.path.join(CACHE_DEM, "town_c_2_2_before_fix_cape.json")   # 直す前の町のデータ
# 陸にする所（海ぞいの大きな駐車場と岸壁）
LAND = [[(4646.0, 4095.8), (4747.0, 4094.4), (4747.5, 4131.0), (4646.0, 4133.0)]]
URBAN = (196, 190, 176)
TILES = [(11, 10), (12, 10), (11, 11), (12, 11)]
# 岬の範囲（この中だけを直す）：師崎港の道（z≈4133）より南
REGION = (4560.0, 4136.0, 4960.0, 4460.0)
BASE = 2.6           # 港の平地の DEM5A の高さ（m）
FOREST = (84, 104, 66)

# 山ぞいの道の、山側の車道の縁（町のデータの車道の形から）。北西 → 南東。擁壁はこの縁から 2m 山側
EDGE = [(4616.1, 4138.6), (4643.7, 4138.0), (4644.9, 4138.3), (4645.8, 4139.1), (4646.8, 4140.7), (4647.4, 4141.2), (4707.2, 4183.2),
        (4723.6, 4194.7), (4725.3, 4195.8), (4731.8, 4200.4), (4739.9, 4206.2), (4756.1, 4217.8), (4765.9, 4224.9), (4771.1, 4228.4),
        (4776.4, 4231.8), (4783.7, 4235.7), (4794.4, 4241.1), (4800.0, 4244.2), (4807.5, 4248.9), (4817.7, 4255.4), (4824.4, 4259.7)]
# （参考）OSM の道の中心線
ROADS = [
    [(4743.5, 4174.8), (4794.3, 4170.2), (4865.2, 4220.8), (4867.6, 4225.2), (4867.4, 4228.9), (4845.3, 4262.2), (4842.1, 4263.9),
     (4838.4, 4262.7), (4803.3, 4239.2), (4777.1, 4225.7), (4731.7, 4193.4), (4648.3, 4135.2)],
    [(4648.3, 4135.2), (4734.8, 4131.5), (4739.6, 4135.8), (4743.5, 4174.8), (4731.7, 4193.4)],
    [(4613.4, 4135.9), (4602.1, 4137.3), (4596.5, 4138.0), (4579.8, 4125.5)],
    [(4648.3, 4135.2), (4613.4, 4135.9)],
    [(4739.6, 4135.8), (4745.3, 4132.3), (4790.5, 4129.4), (4806.7, 4138.1)],
]


def ll_tile(lat, lon, Z):
    n = 2 ** Z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def fetch(url, path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "townscape-sim/1.0"}), timeout=30).read()
        except Exception:
            data = b""
        open(path, "wb").write(data)
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


_img = {}


def dem5a(x, z):
    """DEM5A の標高（m）。値が無いときは None"""
    lat, lon = TL.to_ll(x, z)
    tx, ty = ll_tile(lat, lon, 15)
    key = ("d", int(tx), int(ty))
    if key not in _img:
        _img[key] = fetch("https://cyberjapandata.gsi.go.jp/xyz/dem5a_png/15/%d/%d.png" % (int(tx), int(ty)),
                          os.path.join(CACHE_DEM, "dem5a_15_%d_%d.png" % (int(tx), int(ty))))
    im = _img[key]
    if im is None:
        return None
    fx, fy = (tx - int(tx)) * 256 - 0.5, (ty - int(ty)) * 256 - 0.5
    vals, ws = 0.0, 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            px, py = min(255, max(0, int(math.floor(fx)) + dx)), min(255, max(0, int(math.floor(fy)) + dy))
            r, g, b = im.getpixel((px, py))
            v = r * 65536 + g * 256 + b
            if v == 8388608:
                continue
            if v > 8388608:
                v -= 16777216
            w = (1 - abs(fx - px)) * (1 - abs(fy - py))
            if w <= 0:
                continue
            vals += v * 0.01 * w
            ws += w
    return vals / ws if ws > 0.05 else None


def aerial(x, z):
    lat, lon = TL.to_ll(x, z)
    tx, ty = ll_tile(lat, lon, 18)
    key = ("a", int(tx), int(ty))
    if key not in _img:
        _img[key] = fetch("https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/18/%d/%d.jpg" % (int(tx), int(ty)),
                          os.path.join(CACHE_AIR, "18_%d_%d.jpg" % (int(tx), int(ty))))
    im = _img[key]
    if im is None:
        return None
    return im.getpixel((min(255, int((tx - int(tx)) * 256)), min(255, int((ty - int(ty)) * 256))))


def seg_dist(p, a, b):
    ax, az = a
    bx, bz = b
    dx, dz = bx - ax, bz - az
    L2 = dx * dx + dz * dz
    t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - az) * dz) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - az - t * dz)


def road_dist(p):
    d = 1e9
    for line in ROADS:
        for i in range(len(line) - 1):
            d = min(d, seg_dist(p, line[i], line[i + 1]))
    return d


_RD = None


def road_raster(tiles):
    """町のデータの車道・歩道・分離帯の形を 0.5m のマスに塗り、そこからの距離（m）の表を作る"""
    import cv2
    import numpy as np
    global _RD
    x0, z0, x1, z1 = REGION
    R = 0.5
    W, H = int((x1 - x0) / R) + 1, int((z1 - z0) / R) + 1
    m = np.full((H, W), 255, np.uint8)
    for key, t in tiles.items():
        for name in ("car", "side", "med"):
            if not t.get(name):
                continue
            for rings in TL.read_polys(TL.inflate(t[name])):
                for ri, ring in enumerate(rings):
                    P = np.array([[(key[0] * 400 + p[0] - x0) / R, (key[1] * 400 + p[1] - z0) / R] for p in ring], np.int32)
                    cv2.fillPoly(m, [P], 0 if ri == 0 else 255)
    d = cv2.distanceTransform(m, cv2.DIST_L2, 5) * R
    _RD = (d, R)


def rdist(x, z):
    d, R = _RD
    x0, z0 = REGION[0], REGION[1]
    i, j = int(round((z - z0) / R)), int(round((x - x0) / R))
    if 0 <= i < d.shape[0] and 0 <= j < d.shape[1]:
        return float(d[i, j])
    return 99.0


def edge_side(p):
    """山ぞいの縁からの距離と、山側か（縁の進む向きの右＝南西が山）"""
    best, side = 1e9, False
    for i in range(len(EDGE) - 1):
        a, b = EDGE[i], EDGE[i + 1]
        d = seg_dist(p, a, b)
        if d < best:
            best = d
            side = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) > 0
    return best, side


def weight(x, z):
    """標高を足す割合（0〜1）"""
    w = max(0.0, min(1.0, (rdist(x, z) - 2.5) / 3.0))
    d, hill = edge_side((x, z))
    if hill and d < 12:
        w = min(w, max(0.0, min(1.0, (d - 6.5) / 3.0)))
    return w


def in_region(x, z):
    return REGION[0] <= x <= REGION[2] and REGION[1] <= z <= REGION[3]


def encode_heights(H):
    GN = TL.GN
    out = []
    for i in range(GN):
        v = 0
        for j in range(GN):
            q = int(round(H[i * GN + j] * 10))
            out.append(q - v)
            v = q
    return base64.b64encode(zlib.compress(struct.pack("<%dh" % len(out), *out), 9)).decode()


def main():
    preview = None
    if "--preview" in sys.argv:
        preview = sys.argv[sys.argv.index("--preview") + 1]
    T = TL.Town()
    if not os.path.exists(ORIG):
        os.makedirs(CACHE_DEM, exist_ok=True)
        import shutil
        shutil.copyfile(CHUNK, ORIG)
    chunk = json.load(open(ORIG, encoding="utf-8"))
    tiles = {tuple(t["k"]): t for t in chunk["tiles"]}
    road_raster({k: tiles[k] for k in TILES if k in tiles})
    # 建物の中は森にしない
    blds = []
    for key in TILES:
        t = tiles.get(key)
        if t is None:
            continue
        for ty, h, P in TL.read_buildings(t):
            blds.append([(key[0] * 400 + p[0], key[1] * 400 + p[1]) for p in P])
    # DEM5A の値（4m ごとの点）。無い所は近くの値から補う
    pts = {}
    for key in TILES:
        for r in range(TL.GN):
            for c in range(TL.GN):
                x, z = key[0] * 400 + c * 4, key[1] * 400 + r * 4
                if in_region(x, z):
                    pts[(x, z)] = dem5a(x, z)
    valid = [(p, v) for p, v in pts.items() if v is not None]
    stats = {"raised": 0, "max": 0.0, "forest": 0}
    newH = {}
    for key in TILES:
        t = tiles.get(key)
        if t is None:
            continue
        H = TL.read_heights(t)
        for r in range(TL.GN):
            for c in range(TL.GN):
                x, z = key[0] * 400 + c * 4, key[1] * 400 + r * 4
                if not in_region(x, z):
                    continue
                h0 = H[r * TL.GN + c]
                if h0 < -0.5:
                    continue          # 海
                d = pts.get((x, z))
                if d is None:
                    # 近くの DEM5A から補う（40m 以内、距離の重み）。海岸（もとの標高が低い）に近いほど低く
                    s, w = 0.0, 0.0
                    for (px, pz), v in valid:
                        dd = math.hypot(px - x, pz - z)
                        if dd < 40:
                            ww = 1 / (dd * dd + 4)
                            s += v * ww
                            w += ww
                    if w == 0:
                        continue
                    d = s / w
                    # 海までの距離（4m 格子で 3 マスまで見る）
                    near_sea = 99
                    for rr in range(-3, 4):
                        for cc in range(-3, 4):
                            rr2, cc2 = r + rr, c + cc
                            if 0 <= rr2 < TL.GN and 0 <= cc2 < TL.GN and H[rr2 * TL.GN + cc2] < -0.5:
                                near_sea = min(near_sea, math.hypot(rr, cc) * 4)
                    d = BASE + (d - BASE) * min(1.0, near_sea / 14.0)
                add = max(0.0, d - BASE) * weight(x, z)
                if add > 0.05:
                    H[r * TL.GN + c] = round(h0 + add, 1)
                    stats["raised"] += 1
                    stats["max"] = max(stats["max"], add)
        # 港の陸地
        for r in range(TL.GN):
            for c in range(TL.GN):
                x, z = key[0] * 400 + c * 4, key[1] * 400 + r * 4
                if any(TL.in_poly(Q, x, z) for Q in LAND) and H[r * TL.GN + c] < 0.3:
                    H[r * TL.GN + c] = 0.3
        newH[key] = H
    # 森（4m のマス）：航空写真の緑、または持ち上げて 3m 以上になった所
    newF = {}
    for key in TILES:
        t = tiles.get(key)
        if t is None:
            continue
        F = TL.read_forest(t)
        H = newH[key]
        for r in range(100):
            for c in range(100):
                x, z = key[0] * 400 + c * 4 + 2, key[1] * 400 + r * 4 + 2
                if not in_region(x, z):
                    continue
                hs = [H[(r + a) * TL.GN + c + b] for a in (0, 1) for b in (0, 1)]
                if min(hs) < -0.5:
                    continue
                if rdist(x, z) < 3.0:
                    continue
                de, hill = edge_side((x, z))
                if hill and de < 3.5:
                    continue
                if any(TL.in_poly(B, x, z) for B in blds):
                    continue
                col = aerial(x, z)
                green = col is not None and col[1] > col[0] + 6 and col[1] >= col[2] and sum(col) < 400
                if green or max(hs) >= 3.0:
                    if not F[r][c]:
                        stats["forest"] += 1
                    F[r][c] = 1
                    # 木を置くには標高 0.4m 以上がいる（海岸の森）
                    for a in (0, 1):
                        for b in (0, 1):
                            k = (r + a) * TL.GN + c + b
                            if 0 <= H[k] < 0.6 and weight(x - 2 + b * 4, z - 2 + a * 4) > 0.99:
                                H[k] = 0.6
        newF[key] = F
    print("持ち上げた点 %d（最大 +%.1fm）・森にしたマス %d" % (stats["raised"], stats["max"], stats["forest"]))

    # 確認用の絵：標高（灰色）と森（緑）
    if preview:
        S = 4
        x0, z0, x1, z1 = REGION
        W, Hh = int((x1 - x0) / 4) * S, int((z1 - z0) / 4) * S
        im = Image.new("RGB", (W, Hh), (40, 60, 90))
        px = im.load()
        for key in TILES:
            if key not in newH:
                continue
            H, F = newH[key], newF[key]
            for r in range(100):
                for c in range(100):
                    x, z = key[0] * 400 + c * 4, key[1] * 400 + r * 4
                    if not in_region(x, z):
                        continue
                    h = H[r * TL.GN + c]
                    if h < -0.5:
                        continue
                    v = int(90 + min(160, h * 6))
                    colr = (v // 3, v, v // 3) if F[r][c] else (v, v, v)
                    X, Z = int((x - x0) / 4) * S, int((z - z0) / 4) * S
                    for a in range(S):
                        for b in range(S):
                            if 0 <= X + b < W and 0 <= Z + a < Hh:
                                px[X + b, Z + a] = colr
        im.save(preview)
        print("→", preview)
        return

    # 書きこむ
    for key in TILES:
        t = tiles.get(key)
        if t is None:
            continue
        t["h"] = encode_heights(newH[key])
        F = newF[key]
        bits = bytearray(1250)
        for r in range(100):
            for c in range(100):
                if F[r][c]:
                    k = r * 100 + c
                    bits[k >> 3] |= 1 << (7 - (k & 7))
        t["f"] = base64.b64encode(zlib.compress(bytes(bits), 9)).decode()
        # 地面の色：森のマスを森の色に
        im = Image.open(io.BytesIO(base64.b64decode(t["tex"].split(",", 1)[1])))
        pal = im.getpalette()
        ncol = len(pal) // 3
        idx = None
        for i in range(ncol):
            if tuple(pal[i * 3:i * 3 + 3]) == FOREST:
                idx = i
                break
        if idx is None:
            used = set(im.getdata())
            free = [i for i in range(256) if i not in used]
            idx = free[0]
            pal = pal + [0] * (768 - len(pal))
            pal[idx * 3:idx * 3 + 3] = list(FOREST)
            im.putpalette(pal)
        pix = im.load()
        # 港の陸地：海の色のマスを、町の色に
        uidx = None
        pal = im.getpalette()
        for i in range(len(pal) // 3):
            if tuple(pal[i * 3:i * 3 + 3]) == URBAN:
                uidx = i
                break
        if uidx is not None:
            for r2 in range(200):
                for c2 in range(200):
                    x, z = key[0] * 400 + c2 * 2 + 1, key[1] * 400 + r2 * 2 + 1
                    if any(TL.in_poly(Q, x, z) for Q in LAND):
                        pix[c2, r2] = uidx
        for r in range(100):
            for c in range(100):
                if F[r][c]:
                    for a in (0, 1):
                        for b in (0, 1):
                            pix[c * 2 + b, r * 2 + a] = idx
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        t["tex"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    with open(CHUNK, "w", encoding="utf-8") as f:
        json.dump(chunk, f, ensure_ascii=False, separators=(",", ":"))
    print("書きかえた：", os.path.relpath(CHUNK, ROOT))


if __name__ == "__main__":
    main()
