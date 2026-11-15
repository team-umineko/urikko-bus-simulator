# -*- coding: utf-8 -*-
"""国土地理院の航空写真（シームレス空中写真）を、町の座標で切り出す。建物の向き・駐車場の位置などを確かめるための資料用。
（模型には使わない。見るだけ。出典：国土地理院）

使い方： python tools/aerial.py <中心 x> <中心 z> <半径 m> <出力 jpg> [画像の大きさ=800]
  上が北。townmap.py と同じ範囲・同じ向きになる。50m ごとに目盛り。
"""
import io
import math
import os
import sys
import urllib.request

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import townlib as TL

Z = 18
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "元データ", "地図", "地理院航空写真")


def tile_xy(lat, lon):
    n = 2 ** Z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def get(x, y):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "%d_%d_%d.jpg" % (Z, x, y))
    if not os.path.exists(p):
        url = "https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/%d/%d/%d.jpg" % (Z, x, y)
        try:
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "townscape-sim/1.0"}), timeout=30).read()
        except Exception:
            data = b""
        open(p, "wb").write(data)
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return Image.new("RGB", (256, 256), "gray")


def main():
    cx, cz, R, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    S = int(sys.argv[5]) if len(sys.argv) > 5 else 800
    lat0, lon0 = TL.to_ll(cx - R, cz - R)      # 北西
    lat1, lon1 = TL.to_ll(cx + R, cz + R)      # 南東
    x0, y0 = tile_xy(lat0, lon0)
    x1, y1 = tile_xy(lat1, lon1)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    big = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            big.paste(get(tx, ty), ((tx - tx0) * 256, (ty - ty0) * 256))
    crop = big.crop((int((x0 - tx0) * 256), int((y0 - ty0) * 256), int((x1 - tx0) * 256), int((y1 - ty0) * 256))).resize((S, S), Image.LANCZOS)
    d = ImageDraw.Draw(crop)
    k = S / (2 * R)
    g = math.ceil((cx - R) / 50) * 50
    while g < cx + R:
        u = (g - cx + R) * k
        d.line([(u, 0), (u, S)], fill=(255, 255, 0), width=1)
        d.text((u + 2, 2), str(int(g)), fill=(255, 255, 0))
        g += 50
    g = math.ceil((cz - R) / 50) * 50
    while g < cz + R:
        v = (g - cz + R) * k
        d.line([(0, v), (S, v)], fill=(255, 255, 0), width=1)
        d.text((2, v + 2), str(int(g)), fill=(255, 255, 0))
        g += 50
    crop.save(out, quality=85)
    print("→", out)


if __name__ == "__main__":
    main()
