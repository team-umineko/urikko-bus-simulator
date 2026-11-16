# -*- coding: utf-8 -*-
"""海っ子バスの経路（data/routes.json）で、行きどまりの U ターンをやめ、実際の走り方（ぐるっと回る道）に置きかえる。

花ひろば・総合体育館前（1-140-0）：どの便も北西の道から来て、同じ道を戻る（いままでは体育館の北東の道の行きどまりで U ターン）。
  → 北西の道をそのまま南へ進み、JA の集荷センターの南をまわって、南東の道を北東へ上り、体育館の北東の道を北西へ走りながら停まる。
    体育館の北の角の交差点で左へ曲がり、体育館の北西の道を南西へ戻って、もとの経路に合流する。
豊浜港・魚ひろば（1-080-0）：左回り（高浜 → 魚ひろば → 新居）の便（いままでは乗り場の先で U ターン）。
  → 乗り場に停まったあと、魚ひろばの建物と駐車場のまわりを左回りに一周してから北東へ戻り、
    来た道（2 つの交差点）を逆にたどって国道 247 号に出て（信号 12 番。わき道から出る向き）、右へ曲がって新居へ向かう。
走る道は、2026年11月にストリートビュー・地図で確かめた走り方（ユーザーが地図に描いた線）。

車線の線は、地形タイルの車道の形（data/town の car・alley）から道の中心と幅を測って、左側通行の車線に置く
（幅 5.5m 未満の道はまんなか、それ以上は左の縁から max(1.5, 幅/2 − 1.8) m：ほかの経路と同じ決め方）。
寄り道の部分の 5m ごとの標高は地形の高さ、道幅（左右の車道の縁まで）は車道の形から測る。

使い方： python tools/add_loops.py        （一度つないだ形は routes.json の "loops" に書いておき、二度はつながない）
"""
import json
import math
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import townlib as T  # noqa: E402
from move_stop import cum, pack, pts_of, unpack  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "data", "routes.json")
TRAFFIC = os.path.join(ROOT, "data", "traffic.json")
RES = 0.2   # 車道の形を塗る細かさ（m）
NS = 63
PER = NS * 3 + 3


# ---------- 車道の形 ----------
class RoadMask:
    def __init__(self, x0, z0, x1, z1, town):
        self.x0, self.z0 = x0, z0
        self.W, self.H = int((x1 - x0) / RES) + 1, int((z1 - z0) / RES) + 1
        im = Image.new("L", (self.W, self.H), 0)
        d = ImageDraw.Draw(im)
        holes = []
        for i in range(math.floor(x0 / 400), math.floor(x1 / 400) + 1):
            for j in range(math.floor(z0 / 400), math.floor(z1 / 400) + 1):
                t = town.tile((i, j))
                if not t:
                    continue
                for key in ("car", "alley"):
                    if not t.get(key):
                        continue
                    for rings in T.read_polys(T.inflate(t[key])):
                        for k, ring in enumerate(rings):
                            P = [((i * 400 + p[0] - x0) / RES, (j * 400 + p[1] - z0) / RES) for p in ring]
                            if len(P) < 3:
                                continue
                            if k == 0:
                                d.polygon(P, fill=255)
                            else:
                                holes.append(P)
        for P in holes:
            d.polygon(P, fill=0)
        self.px = im.load()

    def on(self, x, z):
        i, j = int((x - self.x0) / RES), int((z - self.z0) / RES)
        return 0 <= i < self.W and 0 <= j < self.H and self.px[i, j] > 0

    def cast(self, x, z, nx, nz, maxd=15.0):
        """(x, z) から (nx, nz) の向きに、車道の縁までの距離（0.5m までのすき間は越える）"""
        last, d, gap = 0.0, 0.0, 0.0
        while d < maxd:
            d += 0.1
            if self.on(x + nx * d, z + nz * d):
                last, gap = d, 0.0
            else:
                gap += 0.1
                if gap > 0.5:
                    break
        return last


# ---------- 折れ線の道具 ----------
def resample(P, step=1.0):
    c = cum(P)
    L = c[-1]
    n = max(1, int(round(L / step)))
    out, i = [], 0
    for k in range(n + 1):
        s = L * k / n
        while i < len(P) - 2 and c[i + 1] < s:
            i += 1
        u = (s - c[i]) / ((c[i + 1] - c[i]) or 1e-9)
        out.append((P[i][0] + (P[i + 1][0] - P[i][0]) * u, P[i][1] + (P[i + 1][1] - P[i][1]) * u))
    return out


def tangents(P):
    D = []
    for i in range(len(P)):
        a, b = P[max(0, i - 2)], P[min(len(P) - 1, i + 2)]
        dx, dz = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dz) or 1
        D.append((dx / L, dz / L))
    return D


def left(d):
    """進む向き d の左（x＝東、z＝南）"""
    return (d[1], -d[0])


def smooth(v, win):
    out = []
    for i in range(len(v)):
        a, b = max(0, i - win), min(len(v), i + win + 1)
        out.append(sum(v[a:b]) / (b - a))
    return out


def fill_none(v):
    idx = [i for i, x in enumerate(v) if x is not None]
    if not idx:
        return [0.0] * len(v)
    out = list(v)
    for i in range(len(v)):
        if out[i] is not None:
            continue
        lo = max([k for k in idx if k < i], default=None)
        hi = min([k for k in idx if k > i], default=None)
        if lo is None:
            out[i] = v[hi]
        elif hi is None:
            out[i] = v[lo]
        else:
            u = (i - lo) / (hi - lo)
            out[i] = v[lo] * (1 - u) + v[hi] * u
    return out


def lane_of(guide, mask, wmax=None):
    """道の中心をたどる線（おおよそ）から、左側通行の車線の中心の線（1m ごと）を作る。
    交差点などで幅が広がる所（幅が中央値の 1.35 倍より大きい・wmax より大きい）は、前後の値でつなぐ"""
    P = resample(guide, 1.0)
    for it in range(3):
        D = tangents(P)
        offs, wid = [], []
        for p, d in zip(P, D):
            n = left(d)
            if not mask.on(*p):
                offs.append(None)
                wid.append(None)
                continue
            l, r = mask.cast(p[0], p[1], n[0], n[1]), mask.cast(p[0], p[1], -n[0], -n[1])
            offs.append((l - r) / 2)
            wid.append(l + r)
        ws = sorted(w for w in wid if w is not None)
        med = ws[len(ws) // 2] if ws else 6.0
        lim = min(med * 1.35, wmax or 1e9)
        for i in range(len(P)):
            if wid[i] is None or wid[i] > lim:
                offs[i] = None
                wid[i] = None
        offs = smooth(fill_none(offs), 8)
        wid = smooth(fill_none(wid), 8)
        P = [(p[0] + left(d)[0] * o, p[1] + left(d)[1] * o) for p, d, o in zip(P, D, offs)]
        P = resample([P[0]] + [((P[i - 1][0] + P[i][0] + P[i + 1][0]) / 3, (P[i - 1][1] + P[i][1] + P[i + 1][1]) / 3) for i in range(1, len(P) - 1)] + [P[-1]], 1.0)
        if len(wid) != len(P):
            wid = [wid[min(len(wid) - 1, int(i * len(wid) / len(P)))] for i in range(len(P))]
    D = tangents(P)
    out = []
    for p, d, w in zip(P, D, wid):
        lat = 0.0 if w < 5.5 else min(w / 2 - 1.5, 1.8)
        n = left(d)
        out.append((p[0] + n[0] * lat, p[1] + n[1] * lat))
    return out


def lane_straight(a, b, mask, ext=0.0):
    """まっすぐな道：a → b の線の上で道の中心のずれと幅を測り、その中央値で車線の線（1m ごと）を作る。
    わき道・駐車場の入口で幅が広がる所に引っぱられないように、幅が中央値の 1.15 倍をこえる所は数えない"""
    d = unit(a, b)
    n = left(d)
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    offs, wid = [], []
    for k in range(int(L) + 1):
        p = (a[0] + d[0] * k, a[1] + d[1] * k)
        if not mask.on(*p):
            continue
        l, r = mask.cast(p[0], p[1], n[0], n[1]), mask.cast(p[0], p[1], -n[0], -n[1])
        offs.append((l - r) / 2)
        wid.append(l + r)
    med = sorted(wid)[len(wid) // 2]
    good = [(o, w) for o, w in zip(offs, wid) if w <= med * 1.15]
    o = sorted(g[0] for g in good)[len(good) // 2]
    w = sorted(g[1] for g in good)[len(good) // 2]
    lat = o + (0.0 if w < 5.5 else min(w / 2 - 1.5, 1.8))
    if os.environ.get("LOOPS_DEBUG"):
        print("  道 %s→%s 幅 %.1fm 中心のずれ %.2fm 車線 %.2fm" % (a, b, w, o, lat))
    s0, s1 = -ext, L + ext
    return [(a[0] + d[0] * s + n[0] * lat, a[1] + d[1] * s + n[1] * lat) for s in [s0 + (s1 - s0) * i / max(1, int(s1 - s0)) for i in range(max(1, int(s1 - s0)) + 1)]]


def trim(P, a, b):
    """折れ線の始めの a m・終わりの b m を落とす"""
    c = cum(P)
    L = c[-1]
    return [p for p, s in zip(P, c) if a <= s <= L - b]


def bezier(p0, d0, p3, d3, k=0.42, step=0.8):
    D = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    h = k * D
    p1 = (p0[0] + d0[0] * h, p0[1] + d0[1] * h)
    p2 = (p3[0] - d3[0] * h, p3[1] - d3[1] * h)
    n = max(4, int(math.ceil(D / step)))
    out = []
    for i in range(1, n):
        t = i / n
        a, b, c, e = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
    return out


def unit(a, b):
    dx, dz = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dz) or 1
    return (dx / L, dz / L)


# ---------- もとの経路 ----------
class Route:
    def __init__(self, P):
        self.P = P
        self.xy = pts_of(P)
        self.c = cum(self.xy)
        self.s0 = P["s0"]

    def seg(self, s):
        c = self.c
        lo, hi = 0, len(c) - 1
        if s <= c[0]:
            return 0
        if s >= c[hi]:
            return hi - 1
        while hi - lo > 1:
            m = (lo + hi) // 2
            if c[m] <= s:
                lo = m
            else:
                hi = m
        return lo

    def pos(self, s):
        i = self.seg(s)
        u = (s - self.c[i]) / ((self.c[i + 1] - self.c[i]) or 1e-9)
        a, b = self.xy[i], self.xy[i + 1]
        return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)

    def dir(self, s):
        return unit(self.pos(s - 2), self.pos(s + 2))

    def proj(self, p, s_lo, s_hi):
        """点 p に一番近い所の道のり（絶対：経路の始まりから）と距離。s_lo〜s_hi の中だけ探す"""
        best, bs = 1e9, None
        for i in range(self.seg(s_lo), self.seg(s_hi) + 1):
            (ax, az), (bx, bz) = self.xy[i], self.xy[i + 1]
            dx, dz = bx - ax, bz - az
            L2 = dx * dx + dz * dz
            t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - az) * dz) / L2))
            d = math.hypot(p[0] - ax - t * dx, p[1] - az - t * dz)
            if d < best:
                best, bs = d, self.c[i] + t * math.sqrt(L2)
        return bs, best


def expand_lim(P):
    out = []
    L = P.get("lim") or []
    for i in range(0, len(L) - 1, 2):
        out += [L[i]] * L[i + 1]
    return out


def rle(v):
    out = []
    for x in v:
        if out and out[-2] == x:
            out[-1] += 1
        else:
            out += [x, 1]
    return out


def sample(arr, s, step=5.0):
    k = s / step
    if k <= 0:
        return arr[0]
    if k >= len(arr) - 1:
        return arr[-1]
    i = int(k)
    u = k - i
    return arr[i] * (1 - u) + arr[i + 1] * u


def build_detour(R, sA, sB, legs, mask):
    """もとの経路の sA から、legs（[(車線の線, cls, lim)]）を順に曲がってつなぎ、sB でもとの経路に戻る点の列 [(x, z, cls, lim)]"""
    out = []
    p, d = R.pos(sA), R.dir(sA)
    for lane, cl, lm in legs:
        q, e = lane[0], unit(lane[0], lane[min(3, len(lane) - 1)])
        for b in bezier(p, d, q, e):
            out.append((b[0], b[1], cl, lm))
        for x in lane:
            out.append((x[0], x[1], cl, lm))
        p, d = lane[-1], unit(lane[max(0, len(lane) - 4)], lane[-1])
    q, e = R.pos(sB), R.dir(sB)
    cl, lm = legs[-1][1], legs[-1][2]
    for b in bezier(p, d, q, e):
        out.append((b[0], b[1], cl, lm))
    return out


def splice(P, R, sA, sB, new, mask, town, stop_k=None, stop_xy=None, pad=None, sigs=()):
    """経路 P の sA〜sB（絶対の道のり）を new に置きかえる。停留所・信号・停止線・5m ごとの値・停留所の板もそろえる"""
    xy, c = R.xy, R.c
    olim = expand_lim(P)
    ocls = P["cls"]
    X, Z, CL, LM = [], [], [], []

    def push(x, z, cl, lm):
        x, z = round(x * 10) / 10, round(z * 10) / 10
        if X and math.hypot(x - X[-1], z - Z[-1]) < 0.3:
            return
        if X:
            CL.append(cl)
            LM.append(lm)
        X.append(x)
        Z.append(z)

    i = 0
    while c[i] < sA - 0.05:
        push(xy[i][0], xy[i][1], ocls[max(0, i - 1)], olim[max(0, i - 1)] if olim else 40)
        i += 1
    ia = R.seg(sA)
    pa = R.pos(sA)
    push(pa[0], pa[1], ocls[ia], olim[ia] if olim else 40)
    nA = len(X) - 1
    for x, z, cl, lm in new:
        push(x, z, cl, lm)
    ib = R.seg(sB)
    pb = R.pos(sB)
    push(pb[0], pb[1], new[-1][2], new[-1][3])
    nB = len(X) - 1
    j = ib + 1
    for k in range(j, len(xy)):
        push(xy[k][0], xy[k][1], ocls[k - 1], olim[k - 1] if olim else 40)
    nc = cum(list(zip(X, Z)))
    sA_new, sB_new = nc[nA], nc[nB]
    delta = sB_new - sB
    s0 = P["s0"]

    def mapS(s_rel):
        s = s_rel + s0
        if s <= sA:
            return s_rel
        if s >= sB:
            return s_rel + delta
        return None

    NR = Route({"pts": [v for p in zip(X, Z) for v in (int(round(p[0] * 10)), int(round(p[1] * 10)))], "s0": s0})

    # 停留所
    stopS = []
    for k, s in enumerate(P["stopS"]):
        if k == stop_k:
            sn, dd = NR.proj(stop_xy, sA_new, sB_new + 80)   # 寄り道のあと、もとの経路に戻った所のこともある
            if dd > 6:
                raise RuntimeError("停留所が寄り道の上に乗らない %.1fm" % dd)
            stopS.append(round(sn - s0, 2))
        else:
            v = mapS(s)
            if v is None:
                raise RuntimeError("寄り道の中にほかの停留所がある")
            stopS.append(round(v, 2))
    # 信号：寄り道の中のものは落とし、寄り道で通る信号を足す
    sig = []
    for g in P.get("sig", []):
        if isinstance(g, dict):
            s, b = mapS(g["s"]), mapS(g["b"])
            if s is None or b is None:
                continue
            g = dict(g, s=round(s, 1), b=round(b, 1))
        else:
            g = mapS(g)
            if g is None:
                continue
            g = round(g, 1)
        sig.append(g)
    for S in sigs:
        sc, dc = NR.proj(S["c"], sA_new, sB_new)
        sl, dl = NR.proj(S["line"], sA_new, sB_new)
        if dc > 12 or dl > 6:
            raise RuntimeError("信号 %d が寄り道の上に乗らない %.1f %.1f" % (S["id"], dc, dl))
        sig.append({"s": round(sc - s0, 1), "b": round(sl - s0, 1), "id": S["id"], "g": S["g"], "o": S["o"], "m": S["m"]})
    sig.sort(key=lambda g: g["s"] if isinstance(g, dict) else g)
    stp = [round(v, 1) for v in (mapS(s) for s in P.get("stp", [])) if v is not None]

    # 5m ごとの値
    total = nc[-1]
    n = int(total // 5) + 1
    old = {k: unpack(P[k]) for k in ("elev", "wl", "wr") if P.get(k)}
    grids = {k: [] for k in old}
    for g in range(n):
        s = g * 5.0
        if s <= sA_new:
            for k in old:
                grids[k].append(sample(old[k], s))
        elif s >= sB_new:
            for k in old:
                grids[k].append(sample(old[k], s - delta))
        else:
            p, d = NR.pos(s), NR.dir(s)
            nl = left(d)
            vals = {
                "elev": (town.h_at(p[0], p[1]) or 0) * 100,
                "wl": max(0.5, mask.cast(p[0], p[1], nl[0], nl[1])) * 10,
                "wr": max(0.5, mask.cast(p[0], p[1], -nl[0], -nl[1])) * 10,
            }
            for k in old:
                grids[k].append(vals[k])

    # 停留所の板
    if P.get("pads") and pad is not None and stop_k is not None:
        import base64
        import zlib
        raw = bytearray(zlib.decompress(base64.b64decode(P["pads"])))
        o = stop_k * PER
        if o + PER <= len(raw):
            raw[o:o + PER] = pad(NR, stopS[stop_k] + s0, mask)
        P["pads"] = base64.b64encode(zlib.compress(bytes(raw), 9)).decode()

    P["pts"] = NR.P["pts"]
    P["cls"] = CL
    if P.get("lim"):
        P["lim"] = rle(LM)
    P["stopS"] = stopS
    P["sig"] = sig
    P["stp"] = stp
    P["len"] = round(P["len"] + delta, 2)
    for k in grids:
        P[k] = pack(grids[k])
    return delta


def board_pad(NR, s_stop, mask):
    """停留所の 24m 手前〜7m 先（0.5m ごと）に、車道の左の縁から外へ 2.9m の板（種類 1）。看板は停まる所、ベンチあり"""
    z0, z1, kind = [], [], []
    for j in range(NS):
        s = s_stop + 24 - j * 0.5
        p, d = NR.pos(s), NR.dir(s)
        n = left(d)
        e = mask.cast(p[0], p[1], n[0], n[1])
        a = max(1.3, e - 0.1)
        z0.append(int(round(a * 10)))
        z1.append(int(round((a + 2.9) * 10)))
        kind.append(1)
    return bytes(z0 + z1 + kind + [0, min(255, z0[48] + 4), 1])


# ---------- 2 つの場所 ----------
def gym_plan(mask):
    """花ひろば・総合体育館前：北西の道 → 南へ → JA 集荷センターの南 → 南東の道を北東へ → 体育館の北東の道を北西へ（ここで停まる）"""
    # 道の中心のおおよその点（車道の形から読んだ）
    lane = lane_of([(1264.5, 1848), (1264, 1900), (1263.6, 1930), (1267, 1942), (1274, 1951), (1290, 1959.7), (1300, 1964.4), (1310, 1969),
                    (1320, 1969.8), (1330, 1965.7), (1340, 1958), (1350, 1950), (1362, 1940), (1373.4, 1930), (1383, 1920), (1395.9, 1910),
                    (1407.3, 1900), (1418.5, 1890), (1430, 1880), (1440.9, 1870), (1451, 1860), (1462.5, 1850), (1473, 1840), (1481, 1832),
                    (1486, 1822), (1486.5, 1814), (1484.5, 1808), (1476, 1800), (1466, 1790), (1458, 1782)], mask, wmax=9)
    return [(lane, 4, 40)]


def uo_plan(mask):
    """豊浜港・魚ひろば（左回り）：乗り場 → 南西 → 南東 → 北東 → 北西 → 北東 → 北西 → 北東 → 国道 247 号を南東へ"""
    S = lambda a, b, t0, t1: trim(lane_straight(a, b, mask), t0, t1)
    L = []
    L.append((S((1690, 3088), (1622, 3156), 46, 8), 3, 40))      # 乗り場の先を南西へ（乗り場では縁石に寄っているので、20m ほどかけて車線に戻る）
    L.append((S((1621, 3158), (1653, 3199), 8, 8), 4, 40))       # 建物の南西の道を南東へ
    L.append((S((1653, 3199), (1730, 3134), 8, 9), 4, 40))       # 建物の南東の道を北東へ
    L.append((S((1731, 3134), (1692, 3090), 9, 10), 4, 40))      # 広い道を北西へ
    L.append((S((1692, 3090), (1728, 3048), 10, 8), 3, 40))      # 来た道を北東へ
    L.append((S((1729, 3047), (1681, 2991), 8, 8), 3, 40))       # 北西へ
    L.append((S((1681, 2990), (1738, 2941), 8, 10), 4, 40))      # 北東へ（国道の信号へ）
    L.append((S((1738, 2941), (1814, 3009), 11, 0), 0, 40))      # 国道 247 号を南東へ
    return L


def main():
    R = json.load(open(PATH, encoding="utf-8"))
    TR = json.load(open(TRAFFIC, encoding="utf-8"))
    town = T.Town()
    done = R.setdefault("loops", {})
    gmask = RoadMask(1150, 1650, 1560, 2050, town)
    umask = RoadMask(1580, 2880, 1880, 3260, town)
    sig12 = TR["sig"][12]   # 国道 247 号と魚ひろばへのわき道の交差点：[x, z, o, m]
    for pi, P in enumerate(R["patterns"]):
        key = str(pi)
        got = done.get(key, [])
        st = P["stops"]
        # 花ひろば・総合体育館前
        if "gym" not in got and "1-140-0" in st:
            k = st.index("1-140-0")
            Rt = Route(P)
            sAbs = P["stopS"][k] + P["s0"]
            sA, dA = Rt.proj((1259.0, 1830.0), sAbs - 400, sAbs)         # 北西の道の、交差点の手前
            sB, dB = Rt.proj((1457.0, 1785.0), sAbs + 5, sAbs + 120)     # 行きどまりで回ったあと、北西へ戻る所（乗り場の手前）
            if dA > 4 or dB > 4:
                print("体育館：経路が合わない", pi, dA, dB)
            else:
                new = build_detour(Rt, sA, sB, gym_plan(gmask), gmask)
                gx, gz = T.to_xz(34.718979, 136.935827)
                d = splice(P, Rt, sA, sB, new, gmask, town, stop_k=k, stop_xy=(gx, gz), pad=board_pad)
                got.append("gym")
                print("体育館", pi, "%+.1fm" % d)
        # 豊浜港・魚ひろば（左回り：高浜 → 魚ひろば → 新居）
        if "uo" not in got and "1-080-0" in st:
            k = st.index("1-080-0")
            if 0 < k < len(st) - 1 and st[k - 1] == "1-090-2" and st[k + 1] == "1-070-2":
                Rt = Route(P)
                sAbs = P["stopS"][k] + P["s0"]
                sA = sAbs + 3.0
                sB, dB = Rt.proj((1827.6, 3016.7), sAbs + 50, sAbs + 400)   # 国道 247 号の、新居の手前
                if dB > 4:
                    print("魚ひろば：経路が合わない", pi, dB)
                else:
                    new = build_detour(Rt, sA, sB, uo_plan(umask), umask)
                    S12 = {"id": 12, "c": (sig12[0], sig12[1]), "line": (1723.07, 2950.15), "g": 1, "o": sig12[2], "m": sig12[3]}
                    d = splice(P, Rt, sA, sB, new, umask, town, sigs=[S12])
                    got.append("uo")
                    print("魚ひろば", pi, "%+.1fm" % d)
        if got:
            done[key] = got
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else PATH   # 試すときは --out で別の所に書く
    with open(out, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
