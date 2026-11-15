# -*- coding: utf-8 -*-
"""建物の写真のフォルダを、番号つきの一覧（コンタクトシート）にする。どの写真がどの面かを調べるための下調べ用。

使い方： python tools/photo_sheets.py <写真のフォルダ> <出力フォルダ> [列=6] [1枚の幅=320]
  出力：<出力フォルダ>/sheet_00.jpg …（左上から右へ、ファイル名の順。番号は 0 から）と index.txt（番号とファイル名）
"""
import os
import sys

from PIL import Image, ImageDraw, ImageOps


def main():
    a = sys.argv[1:]
    src, out = a[0], a[1]
    cols = int(a[2]) if len(a) > 2 else 6
    w = int(a[3]) if len(a) > 3 else 320
    rows = 5
    os.makedirs(out, exist_ok=True)
    files = sorted(f for f in os.listdir(src) if f.lower().endswith((".jpg", ".jpeg", ".png", ".heic")))
    h = int(w * 3 / 4)
    with open(os.path.join(out, "index.txt"), "w", encoding="utf-8") as fo:
        for i, f in enumerate(files):
            fo.write("%d\t%s\n" % (i, f))
    for s in range(0, len(files), cols * rows):
        part = files[s:s + cols * rows]
        nr = (len(part) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (w + 4), nr * (h + 4)), "white")
        dr = ImageDraw.Draw(sheet)
        for k, f in enumerate(part):
            im = Image.open(os.path.join(src, f))
            im = ImageOps.exif_transpose(im)
            im.thumbnail((w, h))
            x, y = (k % cols) * (w + 4), (k // cols) * (h + 4)
            sheet.paste(im, (x + (w - im.width) // 2, y + (h - im.height) // 2))
            dr.rectangle([x, y, x + 34, y + 18], fill="black")
            dr.text((x + 4, y + 3), str(s + k), fill="white")
        sheet.save(os.path.join(out, "sheet_%02d.jpg" % (s // (cols * rows))), quality=82)
    print("%d 枚 → %s" % (len(files), out))


if __name__ == "__main__":
    main()
