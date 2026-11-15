# -*- coding: utf-8 -*-
"""海っ子バスの経路（data/routes.json）の左回り（内海駅→南知多町役場→…→師崎港→…→河和駅→内海駅）に、
豊浜南の信号（traffic.json の信号 id 3、「海っ子バス路線の信号.pdf」の 16 番）を足す。

右回りの経路にはこの信号が入っているが、左回りの経路は、南（半月の側）から入って中村の道へまっすぐ抜けるのに入っていなかった。
右回りと同じ道（中村の道＝従道路、g=1）をまっすぐ通るので g=1 にする。停止線は、右回りと同じく交差点の中心の 12m 手前とする。

使い方： python tools/add_signal16_ccw.py   （何度実行しても同じ結果になる。すでに入っている経路には足さない）
"""
import json
import math
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ROUTES = os.path.join(ROOT, "data", "routes.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic.json")
SIG_ID = 3
STOPLINE_BACK = 12.0   # 交差点の中心から停止線まで（右回りの経路の値 12.6m に近い値）


def main():
    with open(ROUTES, encoding="utf-8") as f:
        R = json.load(f)
    with open(TRAFFIC, encoding="utf-8") as f:
        T = json.load(f)
    sx, sz, o, m = T["sig"][SIG_ID][:4]
    added = []
    for pi, P in enumerate(R["patterns"]):
        if any(isinstance(g, dict) and g.get("id") == SIG_ID for g in P["sig"]):
            continue
        a = P["pts"]
        cum, best = 0.0, (1e9, 0.0)
        px = pz = None
        for i in range(0, len(a), 2):
            x, z = a[i] / 10, a[i + 1] / 10
            if px is not None:
                cum += math.hypot(x - px, z - pz)
            px, pz = x, z
            d = math.hypot(x - sx, z - sz)
            if d < best[0]:
                best = (d, cum)
        if best[0] > 8:          # この信号を通らない経路
            continue
        s = round(best[1] - P["s0"], 1)
        if s - STOPLINE_BACK < P["stopS"][0] or s > P["stopS"][-1]:
            continue
        P["sig"].append({"s": s, "b": round(s - STOPLINE_BACK, 1), "id": SIG_ID, "g": 1, "o": o, "m": m})
        P["sig"].sort(key=lambda g: g["s"] if isinstance(g, dict) else g)
        added.append((pi, s))
    with open(ROUTES, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, separators=(",", ":"))
    print("added:", added)


if __name__ == "__main__":
    main()
