# -*- coding: utf-8 -*-
"""海っ子バスの経路（data/routes.json）で、師崎港（3-010-0）の停まる位置を、観光センターの正面の南の端に移す。

GTFS の停留所の点は観光センターの北西の角（海ぞいの道から曲がった所）にあるが、
走行動画（2026-11-08）では、バスは建物の西の正面にそって南へ進み、正面の南の端（バス停の標識が 3 本立つ角）で停まる。

  出発の便：経路の始まり（助走区間 s0）を長くして、停留所を南へずらす。ほかの停留所・信号・一時停止の s はその分へらす。
  到着の便：経路の終わりを、出発の便と同じ道で南へのばす（標高・道幅などの 5m ごとの値も、出発の便の同じ所の値を使う）。
  停留所の板（pads）：その場所は観光センターの前の歩道（模型 MODELS.moro）があるので「歩道（種類 2）」にする。

使い方： python tools/move_stop.py        （何度実行しても同じ結果になるように、もとの位置からの移動量を見て決める）
"""
import base64
import json
import math
import os
import struct
import zlib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "data", "routes.json")
STOP = "3-010-0"
TARGET = (4744.4, 4174.0)      # 新しい停まる位置（標識が前扉と中扉のまんなか）
OLD = (4742.6, 4141.6)         # もとの位置（出発の便の s=0）


def pts_of(P):
    a = P["pts"]
    return [(a[i] / 10, a[i + 1] / 10) for i in range(0, len(a), 2)]


def cum(xy):
    c = [0.0]
    for i in range(1, len(xy)):
        c.append(c[-1] + math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]))
    return c


def proj(xy, c, p, i0=0, i1=None):
    """点 p に一番近い経路上の点の道のり"""
    best, bs = 1e9, 0
    i1 = len(xy) - 1 if i1 is None else i1
    for i in range(i0, i1):
        ax, az = xy[i]
        bx, bz = xy[i + 1]
        dx, dz = bx - ax, bz - az
        L2 = dx * dx + dz * dz
        t = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - az) * dz) / L2))
        d = math.hypot(p[0] - ax - t * dx, p[1] - az - t * dz)
        if d < best:
            best, bs = d, c[i] + t * math.sqrt(L2)
    return bs, best


def unpack(b64):
    raw = zlib.decompress(base64.b64decode(b64))
    a = struct.unpack("<%dh" % (len(raw) // 2), raw)
    out, v = [], 0
    for x in a:
        v += x
        out.append(v)
    return out


def pack(vals):
    out, v = [], 0
    for x in vals:
        q = int(round(x))
        out.append(q - v)
        v = q
    return base64.b64encode(zlib.compress(struct.pack("<%dh" % len(out), *out), 9)).decode()


def sample(arr, s, step=5.0):
    k = s / step
    if k <= 0:
        return arr[0]
    if k >= len(arr) - 1:
        return arr[-1]
    i = int(k)
    u = k - i
    return arr[i] * (1 - u) + arr[i + 1] * u


def pad_block():
    """停留所の 24m 手前〜7m 先（0.5m ごと 63 個）：観光センター前の歩道（種類 2）。標識は停まる位置、車道の縁から 0.6m 外"""
    NS = 63
    z0 = [16] * NS        # 1.6m（走る線から歩道の縁まで）
    z1 = [55] * NS        # 5.5m（建物の正面まで）
    kind = [2] * NS
    return bytes(z0 + z1 + kind + [0, 21, 0])


def main():
    R = json.load(open(PATH, encoding="utf-8"))
    pats = R["patterns"]
    # 出発の便の形（どれも同じ道で始まる）を基準にする
    base = next(P for P in pats if P["stops"][0] == STOP)
    bxy = pts_of(base)
    bc = cum(bxy)
    s_old_from_start = base["s0"]
    s_new_from_start, dnew = proj(bxy, bc, TARGET, 0, 80)
    s_old_check, dold = proj(bxy, bc, OLD, 0, 80)
    print("基準：もとの停留所の道のり %.1f（GTFS の点から %.1fm）・新しい位置 %.1f（%.1fm）" % (s_old_from_start, dold, s_new_from_start, dnew))
    arrays = {k: unpack(base[k]) for k in ("elev", "wl", "wr") if base.get(k)}
    cls_base = base["cls"]
    done = R.setdefault("moved", {})
    NS = 63
    per = NS * 3 + 3
    for pi, P in enumerate(pats):
        key = str(pi)
        if done.get(key):
            continue
        changed = []
        raw = bytearray(zlib.decompress(base64.b64decode(P["pads"]))) if P.get("pads") else None
        # 出発
        if P["stops"][0] == STOP and pts_of(P)[0] == bxy[0]:
            ds = s_new_from_start - P["s0"]
            if ds > 0.5:
                P["s0"] = round(P["s0"] + ds, 2)
                P["stopS"] = [0.0] + [round(v - ds, 2) for v in P["stopS"][1:]]
                P["len"] = round(P["len"] - ds, 2)
                sig = []
                for g in P.get("sig", []):
                    if isinstance(g, dict):
                        g = dict(g)
                        g["s"] = round(g["s"] - ds, 1)
                        if "b" in g:
                            g["b"] = round(g["b"] - ds, 1)
                    else:
                        g = round(g - ds, 1)
                    sig.append(g)
                P["sig"] = sig
                P["stp"] = [round(v - ds, 1) for v in P.get("stp", [])]
                if raw is not None:
                    raw[0:per] = pad_block()
                changed.append("出発 +%.1fm" % ds)
        # 到着
        if P["stops"][-1] == STOP:
            xy = pts_of(P)
            c = cum(xy)
            L_old = c[-1]
            end = xy[-1]
            # 終わりの点に当たる、基準の経路（出発）の道のり
            s_join, dj = proj(bxy, bc, end, 0, 80)
            if dj < 3.0 and s_new_from_start - s_join > 1.0:
                add_pts = [q for q, cq in zip(bxy, bc) if s_join + 0.8 < cq < s_new_from_start]
                add_pts.append(tuple(bxy[0]))   # 仮（下で置きかえる）
                # 新しい位置ちょうどの点
                for i in range(len(bxy) - 1):
                    if bc[i] <= s_new_from_start <= bc[i + 1]:
                        u = (s_new_from_start - bc[i]) / max(1e-9, bc[i + 1] - bc[i])
                        add_pts[-1] = (bxy[i][0] + (bxy[i + 1][0] - bxy[i][0]) * u, bxy[i][1] + (bxy[i + 1][1] - bxy[i][1]) * u)
                        break
                new_xy = xy + add_pts
                nc = cum(new_xy)
                dL = nc[-1] - L_old
                P["pts"] = [int(round(v * 10)) for q in new_xy for v in q]
                # 区間ごとの値（道の種類・制限速度）：のばした区間は、基準の経路の同じ所の値
                for _ in add_pts:
                    pass
                cls = list(P["cls"])
                for q in add_pts:
                    s_here, _ = proj(bxy, bc, q, 0, 80)
                    j = max(0, min(len(cls_base) - 1, next((i for i in range(len(bc) - 1) if bc[i + 1] >= s_here), 0)))
                    cls.append(cls_base[j])
                P["cls"] = cls
                if P.get("lim"):
                    lim = list(P["lim"])
                    lim[-1] += len(add_pts)
                    P["lim"] = lim
                # 5m ごとの値
                for k in ("elev", "wl", "wr"):
                    if not P.get(k) or k not in arrays:
                        continue
                    a = unpack(P[k])
                    n_new = int(math.floor(nc[-1] / 5.0)) + 1
                    for i in range(len(a), n_new):
                        s_here = i * 5.0 - L_old + s_join
                        a.append(sample(arrays[k], s_here))
                    P[k] = pack(a)
                P["len"] = round(P["len"] + dL, 2)
                st = list(P["stopS"])
                st[-1] = round(st[-1] + dL, 2)
                P["stopS"] = st
                if raw is not None:
                    k = len(P["stopS"]) - 1
                    raw[k * per:(k + 1) * per] = pad_block()
                changed.append("到着 +%.1fm" % dL)
        if raw is not None and changed:
            P["pads"] = base64.b64encode(zlib.compress(bytes(raw), 9)).decode()
        if changed:
            done[key] = True
            print("経路 %d：%s" % (pi, "・".join(changed)))
    R["moved"] = done
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(R, f, ensure_ascii=False, separators=(",", ":"))
    print("書きかえた：data/routes.json")


if __name__ == "__main__":
    main()
