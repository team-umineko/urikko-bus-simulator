# 2040年の100mメッシュ人口（推計）を作る
#
# 入力
#   data/popdata.json                                  2020年の100mメッシュ人口（年齢別）
#   元データ/人口/将来推計/500m_mesh_2024_23_GEOJSON.zip  国土数値情報「500mメッシュ別将来推計人口（R6国政局推計）」愛知県
# 出力
#   data/pop2040.json
#
# 方法
#   500mメッシュごと・年齢区分ごとに「2040年の推計 ÷ 2020年の100mメッシュの合計」の倍率を出し、
#   中の100mメッシュに掛ける。2020年の人数が少ない（3人未満）区分は、町全体の倍率を使う。
#   最後に、町ごと・年齢区分ごとの合計が500mメッシュの推計と一致するように全体をそろえる。
#
# 使い方: python -I tools/make_pop2040.py
import json
import math
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POP = ROOT / "data" / "popdata.json"
SRC = ROOT / "元データ" / "人口" / "将来推計" / "500m_mesh_2024_23_GEOJSON.zip"
OUT = ROOT / "data" / "pop2040.json"

TOWN = {"m": "23445", "s": "23445", "k": "23445", "h": "23446"}
GROUPS = ["y", "w", "o65", "o75", "o85"]     # 0〜14歳・15〜64歳・65歳以上・75歳以上・85歳以上


def m500_2040(p):
    return {
        "y": p["PTA_2040"] or 0,
        "w": p["PTB_2040"] or 0,
        "o65": p["PTC_2040"] or 0,
        "o75": p["PTD_2040"] or 0,
        "o85": (p["PT18_2040"] or 0) + (p["PT19_2040"] or 0) + (p["PT20_2040"] or 0),
    }


def main():
    D = json.loads(POP.read_text(encoding="utf-8"))
    G = D["popGrid"]
    with zipfile.ZipFile(SRC) as z:
        name = next(n for n in z.namelist() if n.endswith(".geojson"))
        gj = json.loads(z.read(name))

    # 500mメッシュ：左下の角の緯度経度から番号を作る（1/240度 × 1/160度）
    meshes = {}
    for f in gj["features"]:
        p = f["properties"]
        if p.get("SHICODE") not in ("23445", "23446"):
            continue
        ring = f["geometry"]["coordinates"][0]
        lat = min(c[1] for c in ring)
        lon = min(c[0] for c in ring)
        key = (round(lat * 240), round(lon * 160))
        meshes[key] = {"town": p["SHICODE"], "v40": m500_2040(p), "v20": dict.fromkeys(GROUPS, 0.0), "cells": []}

    cells = []
    for c in G["cells"]:
        row, col, zone, T, y, w, o65, o75, o85 = c
        v = {"y": y / 100, "w": w / 100, "o65": o65 / 100, "o75": o75 / 100, "o85": o85 / 100}
        lat = G["latA"] + (row + 0.5) * G["dLat"]
        lon = G["lonA"] + (col + 0.5) * G["dLon"]
        key = (math.floor(lat * 240), math.floor(lon * 160))
        cell = {"row": row, "col": col, "zone": zone, "v": v, "mesh": meshes.get(key)}
        cells.append(cell)
        if cell["mesh"]:
            cell["mesh"]["cells"].append(cell)
            for g in GROUPS:
                cell["mesh"]["v20"][g] += v[g]

    # 町全体の倍率（予備）
    town_ratio = {}
    for t in ("23445", "23446"):
        ms = [m for m in meshes.values() if m["town"] == t]
        town_ratio[t] = {g: sum(m["v40"][g] for m in ms) / max(1e-9, sum(m["v20"][g] for m in ms)) for g in GROUPS}

    for c in cells:
        t = TOWN[c["zone"]]
        m = c["mesh"]
        c["v40"] = {}
        for g in GROUPS:
            r = town_ratio[t][g]
            if m and m["v20"][g] >= 3:
                r = m["v40"][g] / m["v20"][g]
            c["v40"][g] = c["v"][g] * r

    # 町ごと・年齢区分ごとの合計を、500mメッシュの推計に合わせる
    target = {t: {g: sum(m["v40"][g] for m in meshes.values() if m["town"] == t) for g in GROUPS} for t in ("23445", "23446")}
    for t in ("23445", "23446"):
        cs = [c for c in cells if TOWN[c["zone"]] == t]
        for g in GROUPS:
            s = sum(c["v40"][g] for c in cs)
            k = target[t][g] / s if s > 0 else 1
            for c in cs:
                c["v40"][g] *= k

    out_cells = []
    for c in cells:
        v = c["v40"]
        v["o75"] = min(v["o75"], v["o65"])
        v["o85"] = min(v["o85"], v["o75"])
        T = v["y"] + v["w"] + v["o65"]
        out_cells.append([round(T * 100), round(v["y"] * 100), round(v["w"] * 100), round(v["o65"] * 100), round(v["o75"] * 100), round(v["o85"] * 100)])

    towns = {}
    for t, nm in (("23445", "南知多町"), ("23446", "美浜町")):
        ms = [m for m in meshes.values() if m["town"] == t]
        v40 = {g: round(sum(m["v40"][g] for m in ms)) for g in GROUPS}
        towns[t] = {"name": nm, "pop2040": v40["y"] + v40["w"] + v40["o65"], **v40}

    OUT.write_text(json.dumps({
        "year": 2040,
        "src": "国土数値情報「500mメッシュ別将来推計人口（R6国政局推計）」（国土交通省）を、令和2年国勢調査の100mメッシュ人口に年齢区分ごとの増減率で割り振って作成",
        "fields": ["PopT", "Pop0_14", "Pop15_64", "Pop65over", "Pop75over", "Pop85over"],
        "towns": towns,
        "cells": out_cells,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for t, v in towns.items():
        print(v["name"], v)
    miss = sum(1 for c in cells if not c["mesh"])
    print("cells", len(cells), "500mメッシュが見つからない100mメッシュ", miss, file=sys.stderr)


if __name__ == "__main__":
    main()
