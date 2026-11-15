# -*- coding: utf-8 -*-
"""走行動画から、一定の間隔でコマを取り出して一覧（コンタクトシート）にする。街並みを作るときの下調べ用。

使い方： python tools/video_sheets.py <動画> <出力フォルダ> [間隔(秒)=10] [列=5] [行=4] [1コマの幅=384] [開始(秒)=0] [終了(秒)]
  出力：<出力フォルダ>/sheet_000.jpg …（左上から右へ。1 枚目の左上が 開始 秒）
       コマの時刻 ＝ 開始 ＋（シートの番号 × 列 × 行 ＋ 左上から数えた番号）× 間隔
ffmpeg が必要。
"""
import os
import subprocess
import sys


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        print(__doc__)
        return
    video, out = a[0], a[1]
    step = float(a[2]) if len(a) > 2 else 10
    cols = int(a[3]) if len(a) > 3 else 5
    rows = int(a[4]) if len(a) > 4 else 4
    w = int(a[5]) if len(a) > 5 else 384
    t0 = float(a[6]) if len(a) > 6 else 0
    t1 = float(a[7]) if len(a) > 7 else None
    os.makedirs(out, exist_ok=True)
    vf = "fps=1/%g,scale=%d:-2,tile=%dx%d:padding=4:color=white" % (step, w, cols, rows)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(t0)]
    if t1 is not None:
        cmd += ["-t", str(t1 - t0)]
    cmd += ["-i", video, "-an", "-vf", vf, "-q:v", "4", os.path.join(out, "sheet_%03d.jpg")]
    subprocess.check_call(cmd)
    n = len([f for f in os.listdir(out) if f.startswith("sheet_")])
    print("シート %d 枚（%g 秒ごと・%d×%d）→ %s" % (n, step, cols, rows, out))


if __name__ == "__main__":
    main()
