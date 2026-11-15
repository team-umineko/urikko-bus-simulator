# -*- coding: utf-8 -*-
"""写真の中の壁を「正面から見た画像」に直す。建物の模型を作るときに、窓の割り付けや寸法の比を読み取るための資料用。
（できた画像は見るだけで、シミュレーターには貼らない。建物は写真を貼らずに、形を組み立てて作る）

  目盛りつきで切り出す（角の座標を読むため）：
    python tools/rectify.py grid <写真> <出力 jpg> <x0> <y0> <x1> <y1> [目盛りの間隔=200]
  4 つの角を指定して、正面から見た画像にする（角は 左上・右上・右下・左下 の順。写真のもとの大きさでの座標）：
    python tools/rectify.py warp <写真> <出力> <x,y> <x,y> <x,y> <x,y> <幅 px> <高さ px> [明るさの倍率=1]
写真は、撮ったときの向き（EXIF）に直してから使う。
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageOps


def load(path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def save(path, img):
    ext = os.path.splitext(path)[1].lower()
    rgb = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if ext == ".webp":
        rgb.save(path, "WEBP", quality=82, method=6)
    elif ext in (".jpg", ".jpeg"):
        rgb.save(path, "JPEG", quality=86)
    else:
        rgb.save(path)


def grid(a):
    src, out = a[0], a[1]
    x0, y0, x1, y1 = [int(float(v)) for v in a[2:6]]
    step = int(a[6]) if len(a) > 6 else 200
    img = load(src)
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    c = img[y0:y1, x0:x1].copy()
    k = min(1400 / c.shape[1], 1100 / c.shape[0])
    c = cv2.resize(c, (int(c.shape[1] * k), int(c.shape[0] * k)), interpolation=cv2.INTER_AREA)
    x = (x0 // step + 1) * step
    while x < x1:
        u = int((x - x0) * k)
        cv2.line(c, (u, 0), (u, c.shape[0]), (0, 255, 255), 1)
        cv2.putText(c, str(x), (u + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
        cv2.putText(c, str(x), (u + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        x += step
    y = (y0 // step + 1) * step
    while y < y1:
        v = int((y - y0) * k)
        cv2.line(c, (0, v), (c.shape[1], v), (0, 255, 255), 1)
        cv2.putText(c, str(y), (2, v - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
        cv2.putText(c, str(y), (2, v - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        y += step
    save(out, c)
    print("写真 %d×%d、切り出し (%d,%d)-(%d,%d)、倍率 %.3f → %s" % (W, H, x0, y0, x1, y1, k, out))


def warp(a):
    src, out = a[0], a[1]
    pts = np.array([[float(v) for v in p.split(",")] for p in a[2:6]], np.float32)
    w, h = int(a[6]), int(a[7])
    gain = float(a[8]) if len(a) > 8 else 1.0
    img = load(src)
    M = cv2.getPerspectiveTransform(pts, np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32))
    o = cv2.warpPerspective(img, M, (w, h), flags=cv2.INTER_AREA if w < 600 else cv2.INTER_LINEAR)
    if gain != 1.0:
        o = np.clip(o.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    save(out, o)
    print("→ %s（%d×%d、%.0f KB）" % (out, w, h, os.path.getsize(out) / 1024))


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("grid", "warp"):
        print(__doc__)
    elif sys.argv[1] == "grid":
        grid(sys.argv[2:])
    else:
        warp(sys.argv[2:])
