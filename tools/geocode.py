# -*- coding: utf-8 -*-
"""施設の名前・住所から場所（緯度・経度と、町のデータの x・z）を調べる。
国土地理院の地名検索と、OpenStreetMap の Nominatim を使う（どちらも公開の検索。出典の明示が必要）。

使い方： python tools/geocode.py 名前1 名前2 …
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import townlib as TL

UA = {"User-Agent": "townscape-sim/1.0 (school research project)"}


def get(url):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30))
    except Exception as e:
        return {"error": str(e)}


for q in sys.argv[1:]:
    print("■", q)
    r = get("https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(q))
    if isinstance(r, list):
        for f in r[:6]:
            lon, lat = f["geometry"]["coordinates"]
            if 34.66 < lat < 34.82 and 136.83 < lon < 137.0:
                x, z = TL.to_xz(lat, lon)
                print("  地理院  %s  %.5f,%.5f  x=%.0f z=%.0f" % (f["properties"].get("title"), lat, lon, x, z))
    time.sleep(1.1)
    r = get("https://nominatim.openstreetmap.org/search?format=json&limit=5&viewbox=136.83,34.82,137.0,34.66&bounded=1&q=" + urllib.parse.quote(q))
    if isinstance(r, list):
        for f in r:
            lat, lon = float(f["lat"]), float(f["lon"])
            x, z = TL.to_xz(lat, lon)
            print("  OSM     %s  %.5f,%.5f  x=%.0f z=%.0f" % (f.get("display_name", "")[:50], lat, lon, x, z))
    else:
        print("  OSM", r)
    time.sleep(1.1)
