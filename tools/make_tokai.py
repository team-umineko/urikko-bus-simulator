# 人口分布の画面で、周りに出す東海3県（愛知・岐阜・三重）とほかの都道府県の形を作る（海は画面の側で塗る）
#
# 入力  元データ/地図/地球地図日本/japan.geojson（地球地図日本・国土地理院 を dataofjapan/land が GeoJSON にしたもの）
# 出力  data/tokai.json
#   prefs: [{ id, n（名前）, k（1＝東海3県、0＝ほかの都道府県）, rings: [[x, z, x, z, ...], ...] }]
#   box: 東海3県と太平洋が入る範囲（カメラが動ける範囲に使う）
#   座標は popdata.json と同じ（原点 lat0/lon0、x＝東向き m、z＝南向き m）。10m 単位の整数
#
# 使い方: python -I tools/make_tokai.py
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "元データ" / "地図" / "地球地図日本" / "japan.geojson"
OUT = ROOT / "data" / "tokai.json"
O = json.loads((ROOT / "data" / "popdata.json").read_text(encoding="utf-8"))["origin"]

# カメラが動ける範囲（太平洋まで入るよう南に広め）
BOX = (135.3, 32.9, 138.5, 36.65)   # 西・南・東・北
TOKAI = {21, 23, 24}
NEAR = {16, 17, 18, 19, 20, 22, 25, 26, 27, 28, 29, 30}
# 線の単純化（度）と、省く小さな島の面積（度²）。東海3県はくわしく、遠い所はあらく
TOL = {"tokai": 0.0025, "near": 0.005, "far": 0.015}
MIN_AREA = {"tokai": 0.0004, "near": 0.001, "far": 0.004}


def simplify(pts, tol):
    # Douglas–Peucker（輪の始点と、始点からいちばん遠い点で2つに分けて行う）
    if len(pts) < 5:
        return pts
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    return dp(pts[: far + 1], tol)[:-1] + dp(pts[far:] + [pts[0]], tol)[:-1]


def dp(pts, tol):
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, bi = -1, -1
        for i in range(a + 1, b):
            d = abs((pts[i][0] - ax) * dy - (pts[i][1] - ay) * dx) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def area(r):
    return abs(sum(r[i - 1][0] * r[i][1] - r[i][0] * r[i - 1][1] for i in range(len(r)))) / 2


def to_xz(p):
    return [round((p[0] - O["lon0"]) * O["kx"] / 10), round(-(p[1] - O["lat0"]) * O["kz"] / 10)]


def main():
    gj = json.loads(SRC.read_text(encoding="utf-8"))
    prefs = []
    for f in gj["features"]:
        pid = f["properties"]["id"]
        grp = "tokai" if pid in TOKAI else "near" if pid in NEAR else "far"
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = []
        for poly in polys:
            outer = [tuple(p) for p in poly[0][:-1]]
            if area(outer) < MIN_AREA[grp]:
                continue
            r = simplify(outer, TOL[grp])
            if len(r) < 3 or area(r) < MIN_AREA[grp] / 4:
                continue
            flat = []
            for p in r:
                flat += to_xz(p)
            rings.append(flat)
        if rings:
            prefs.append({"id": pid, "n": f["properties"]["nam_ja"], "k": 1 if grp == "tokai" else 0, "rings": rings})
    x0, z1 = to_xz((BOX[0], BOX[1]))
    x1, z0 = to_xz((BOX[2], BOX[3]))
    OUT.write_text(json.dumps({
        "src": "地球地図日本（国土地理院）を加工して作成",
        "unit": 10,
        "box": [x0 * 10, z0 * 10, x1 * 10, z1 * 10],
        "prefs": prefs,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(len(prefs), sum(len(r) // 2 for p in prefs for r in p["rings"]), "points", OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
