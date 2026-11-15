# -*- coding: utf-8 -*-
"""横断歩道を道路と直角に直す（data/traffic.json を書きかえる）。

もとのデータでは、斜めに交わる交差点の横断歩道が「平行四辺形」になっていて、
縞の端が斜めにずれていた（256 か所のうち 58 か所で 8°以上）。
実際の横断歩道は、縞が道路の向きと平行で、縞の端は道路と直角の線にそろう。

直し方（帯ごと）：
  ・縞の向き（＝道路の向き）d はそのまま使う。横切る向き n は d と直角にする。
  ・帯の中心は動かさない。横切る幅は、もとの帯を n に投影した幅（＝道路の幅）。
  ・縞は幅 0.45m・間隔 0.45m で、中心から左右対称に並べ直す。
  ・帯に沿って斜めに引かれていた停止線も、道路と直角にして、横断歩道との間隔を保つ。

使い方： python tools/fix_crosswalks.py        （data/traffic.json を直す）
        python tools/fix_crosswalks.py --dry  （数だけ数える）
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "data", "traffic.json")
STRIPE_W = 0.45      # 縞の幅
PITCH = 0.90         # 縞の中心から次の縞の中心まで
MIN_DEV = 0.75       # これより歪みの小さい帯（度）は触らない


def inpoly(P, x, z):
    c = False
    for i in range(len(P)):
        a, b = P[i], P[i - 1]
        if (a[1] > z) != (b[1] > z) and x < (b[0] - a[0]) * (z - a[1]) / (b[1] - a[1]) + a[0]:
            c = not c
    return c


def r2(v):
    return round(v, 2)


def main(dry=False):
    tr = json.load(open(PATH, encoding="utf-8"))
    T = tr["t"]
    bands = []          # (タイルの名前, 帯の番号, 4 つの角)
    for k, v in T.items():
        for bi, b in enumerate(v.get("xb", [])):
            bands.append((k, bi, [(b[i], b[i + 1]) for i in range(0, 8, 2)]))
    # 縞を帯に割り当てる（縞の中心が入っている帯）
    owner = {}          # (タイル, 縞の番号) -> 帯の番号（bands の添字）
    for k, v in T.items():
        for si, s in enumerate(v.get("cw", [])):
            n = len(s) // 2
            cx = sum(s[0::2]) / n
            cz = sum(s[1::2]) / n
            for gi, (_, _, P) in enumerate(bands):
                if inpoly(P, cx, cz):
                    owner[(k, si)] = gi
                    break
    fixed = 0
    fixed_sl = 0
    remove = {}         # タイル -> 消す縞の番号
    add = {}            # タイル -> 足す縞
    for gi, (bk, bi, P) in enumerate(bands):
        mine = [(k, si) for (k, si), g in owner.items() if g == gi]
        if not mine:
            continue
        # 縞の向き：縞の長い辺の向きの平均（向きをそろえてから平均する）
        dx = dz = 0.0
        lens = []
        ms = []
        for k, si in mine:
            s = T[k]["cw"][si]
            m = len(s) // 4
            ux, uz = s[2 * (m - 1)] - s[0], s[2 * (m - 1) + 1] - s[1]
            L = math.hypot(ux, uz)
            if L < 0.5:
                continue
            if ux * dx + uz * dz < 0:
                ux, uz = -ux, -uz
            dx += ux
            dz += uz
            lens.append(L)
            ms.append(m)
        L = math.hypot(dx, dz)
        if L < 1e-6:
            continue
        d = (dx / L, dz / L)
        n = (d[1], -d[0])
        e0 = (P[1][0] - P[0][0], P[1][1] - P[0][1])
        e1 = (P[2][0] - P[1][0], P[2][1] - P[1][1])
        # 帯のどちらの辺が「横切る向き」か：縞の向きと直角に近い方
        if abs(e0[0] * d[0] + e0[1] * d[1]) / math.hypot(*e0) > abs(e1[0] * d[0] + e1[1] * d[1]) / math.hypot(*e1):
            e0, e1 = e1, e0
        cosang = (e0[0] * e1[0] + e0[1] * e1[1]) / (math.hypot(*e0) * math.hypot(*e1))
        dev = abs(90 - math.degrees(math.acos(max(-1, min(1, cosang)))))
        if dev < MIN_DEV:
            continue
        c = (sum(p[0] for p in P) / 4, sum(p[1] for p in P) / 4)
        along = abs(e1[0] * d[0] + e1[1] * d[1])          # 帯の、道路に沿った長さ
        across = abs(e0[0] * n[0] + e0[1] * n[1])         # 帯の、道路を横切る幅（道路の幅）
        shear = (e0[0] * d[0] + e0[1] * d[1]) / (e0[0] * n[0] + e0[1] * n[1])   # 横に 1m 進むと、道路に沿って何 m ずれていたか
        # もとの縞が、横切る向きにどこからどこまで並んでいたか
        bs = []
        for k, si in mine:
            s = T[k]["cw"][si]
            m2 = len(s) // 2
            cx = sum(s[0::2]) / m2
            cz = sum(s[1::2]) / m2
            bs.append((cx - c[0]) * n[0] + (cz - c[1]) * n[1])
        span = max(bs) - min(bs) + STRIPE_W
        mid = (max(bs) + min(bs)) / 2
        cnt = max(1, int(math.floor((span - STRIPE_W) / PITCH + 1e-6)) + 1)
        SL = sum(lens) / len(lens)                         # 縞の長さ
        m = max(2, int(round(sum(ms) / len(ms))))          # 縞の長い辺の点の数（地面に沿わせるための区切り）
        new = []
        for i in range(cnt):
            b = mid + (i - (cnt - 1) / 2) * PITCH
            left = []
            right = []
            for j in range(m):
                a = -SL / 2 + SL * j / (m - 1)
                left.append((c[0] + d[0] * a + n[0] * (b - STRIPE_W / 2), c[1] + d[1] * a + n[1] * (b - STRIPE_W / 2)))
                right.append((c[0] + d[0] * a + n[0] * (b + STRIPE_W / 2), c[1] + d[1] * a + n[1] * (b + STRIPE_W / 2)))
            ring = left + right[::-1]
            new.append([r2(v) for p in ring for v in p])
        for k, si in mine:
            remove.setdefault(k, set()).add(si)
        add.setdefault(mine[0][0], []).extend(new)
        # 帯（中央線を切る範囲）を長方形に
        hw, hl = across / 2, along / 2
        rect = [(-hl, -hw), (-hl, hw), (hl, hw), (hl, -hw)]
        if not dry:
            T[bk]["xb"][bi] = [r2(v) for a, b in rect for v in (c[0] + d[0] * a + n[0] * b, c[1] + d[1] * a + n[1] * b)]
        # 停止線：この帯のすぐ手前（15m 以内）にあり、もとの帯の斜めの辺と平行だったものを、道路と直角にする
        for k, v in T.items():
            for sl in v.get("sl", []):
                mx, mz = (sl[0] + sl[2]) / 2, (sl[1] + sl[3]) / 2
                a = (mx - c[0]) * d[0] + (mz - c[1]) * d[1]
                b = (mx - c[0]) * n[0] + (mz - c[1]) * n[1]
                if abs(a) > hl + 6 or abs(b) > hw + 1.5:
                    continue
                sx, sz = sl[2] - sl[0], sl[3] - sl[1]
                sL = math.hypot(sx, sz)
                if sL < 0.3:
                    continue
                off = abs(math.degrees(math.asin(max(-1, min(1, (sx * d[0] + sz * d[1]) / sL)))))   # 道路と直角からのずれ
                if off < 1.0:
                    continue
                a2 = a - shear * b                       # 横断歩道との間隔はそのまま
                h = abs(sx * n[0] + sz * n[1]) / 2       # 横切る向きの長さの半分
                sgn = 1 if (sx * n[0] + sz * n[1]) >= 0 else -1
                p = (c[0] + d[0] * a2 + n[0] * (b - sgn * h), c[1] + d[1] * a2 + n[1] * (b - sgn * h))
                q = (c[0] + d[0] * a2 + n[0] * (b + sgn * h), c[1] + d[1] * a2 + n[1] * (b + sgn * h))
                if not dry:
                    sl[0], sl[1], sl[2], sl[3] = r2(p[0]), r2(p[1]), r2(q[0]), r2(q[1])
                fixed_sl += 1
        fixed += 1
    if not dry:
        for k, idx in remove.items():
            T[k]["cw"] = [s for i, s in enumerate(T[k]["cw"]) if i not in idx]
        for k, new in add.items():
            T[k]["cw"].extend(new)
        json.dump(tr, open(PATH, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"横断歩道 {len(bands)} か所のうち {fixed} か所を直角に直した。停止線 {fixed_sl} 本を直した。")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
