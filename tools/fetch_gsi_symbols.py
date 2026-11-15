# -*- coding: utf-8 -*-
"""国土地理院「地理院地図 Vector」から、植生の地図記号（田・畑・果樹園など）の位置を集める。

出力：元データ/地図/地理院地図Vector/symbols.json
  { "src": 出典, "codes": {コード: 名前}, "pts": [[緯度, 経度, コード], ...] }
タイル（z14）は 元データ/地図/地理院地図Vector/tiles/ に保存する（2 回目からは読み直さない）。

出典：国土地理院ベクトルタイル（地理院地図 Vector）。利用は国土地理院コンテンツ利用規約による（出典の明示が必要）。
使い方： python tools/fetch_gsi_symbols.py
"""
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mvt  # noqa: E402

ROOT = os.path.join(HERE, "..")
OUT = os.path.join(ROOT, "元データ", "地図", "地理院地図Vector")
TILES = os.path.join(OUT, "tiles")
Z = 14
# 町のデータ（data/town）がある範囲より少し広く
LAT0, LAT1, LON0, LON1 = 34.685, 34.805, 136.845, 136.995
CODES = {6311: "田", 6312: "畑", 6313: "茶畑", 6314: "果樹園", 6321: "広葉樹林", 6322: "針葉樹林", 6323: "竹林", 6324: "ヤシ科樹林", 6325: "ハイマツ地", 6326: "笹地", 6327: "荒地"}


def tile_xy(lat, lon, z):
    x = (lon + 180) / 360 * 2 ** z
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** z
    return x, y


def tile_ll(x, y, z):
    lon = x / 2 ** z * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))
    return lat, lon


def main():
    os.makedirs(TILES, exist_ok=True)
    x0, y1 = tile_xy(LAT0, LON0, Z)
    x1, y0 = tile_xy(LAT1, LON1, Z)
    pts = {}
    n = 0
    for x in range(int(x0), int(x1) + 1):
        for y in range(int(y0), int(y1) + 1):
            p = os.path.join(TILES, "%d_%d_%d.pbf" % (Z, x, y))
            if not os.path.exists(p):
                url = "https://cyberjapandata.gsi.go.jp/xyz/experimental_bvmap/%d/%d/%d.pbf" % (Z, x, y)
                try:
                    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "townscape-sim/1.0"}), timeout=40).read()
                except Exception as e:      # 海だけのタイルは無い
                    print("なし", x, y, e)
                    data = b""
                open(p, "wb").write(data)
                time.sleep(0.3)
            data = open(p, "rb").read()
            if not data:
                continue
            n += 1
            ext = mvt.layer_extent(data).get("symbol", 4096)
            for ft in mvt.decode(data).get("symbol", []):
                c = ft["props"].get("ftCode")
                if c not in CODES or not ft["geom"]:
                    continue
                px, py = ft["geom"][0][0]
                if not (0 <= px < ext and 0 <= py < ext):     # となりのタイルと重なる分は数えない
                    continue
                lat, lon = tile_ll(x + px / ext, y + py / ext, Z)
                pts[(round(lat, 6), round(lon, 6), c)] = 1
    out = {"src": "国土地理院ベクトルタイル（地理院地図 Vector）の植生の記号。2万5千分1地形図相当", "codes": {str(k): v for k, v in CODES.items()}, "pts": [list(k) for k in sorted(pts)]}
    json.dump(out, open(os.path.join(OUT, "symbols.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    cnt = {}
    for k in pts:
        cnt[CODES[k[2]]] = cnt.get(CODES[k[2]], 0) + 1
    print("タイル", n, "枚・記号", len(pts), "個", cnt)


if __name__ == "__main__":
    main()
