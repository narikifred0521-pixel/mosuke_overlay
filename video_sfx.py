"""配信した動画に、あとから効果音を綺麗に載せる。

動画に映っているオーバーレイの表示（クリアの黄色いマス／ミスの赤い丸）が増えた瞬間を
読み取って、その時刻に効果音を重ねた動画を書き出す。
スマホ配信でマイク越しに音が入ってしまう問題を、編集側で解決するためのもの。

  python3 video_sfx.py 入力.mov                     # 入力_SE付き.mp4 を書き出す
  python3 video_sfx.py 入力.mov --dry-run           # 検出した時刻の一覧だけ出す
  python3 video_sfx.py 入力.mov --out 出力.mp4 --gain 0.8

必要なもの: ffmpeg / ffprobe / numpy
"""
import argparse
import csv
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
SFX_DIR = HERE / "sfx"

# オーバーレイの色（common.js / overlay.html と同じ）
HUD_BG = (0x2B, 0x34, 0x50)
GOLD = (0xF0, 0xB4, 0x29)
RED = (0xE0, 0x1F, 0x33)

FPS = 10           # 解析するフレームレート（1投ずつの判別はこれで十分）
MIN_GAP = 0.6      # これより近い検出はまとめる（秒）


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def probe(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", str(path)]).stdout.decode()
    w, h, dur = out.split()
    return int(w), int(h), float(dur)


def frames(path, fps, w, h, crop=None):
    """動画をRGBのnumpy配列として順に返す。"""
    vf = f"fps={fps}"
    if crop:
        x0, y0, cw, ch = crop
        vf += f",crop={cw}:{ch}:{x0}:{y0}"
        w, h = cw, ch
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf,
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = w * h * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    p.stdout.close()
    p.wait()


def near(img, color, tol=26):
    """その色に近いピクセルのマスク。"""
    d = np.abs(img.astype(np.int16) - np.array(color, np.int16))
    return (d.max(axis=2) <= tol)


def longest_run(mask):
    """Trueがいちばん長く続く区間 (start, end) を返す。"""
    best = cur = None
    for i, v in enumerate(mask):
        if v:
            cur = (cur[0], i) if cur else (i, i)
            if best is None or cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            cur = None
    return best


def find_hud(path, dur, w, h):
    """種目表示パネル（紺の角丸）の位置を探す。動画の数か所を見て、いちばん確からしい場所を採る。"""
    boxes = []
    for t in np.linspace(dur * 0.05, dur * 0.95, 9):
        out = run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
        if len(out) < w * h * 3:
            continue
        img = np.frombuffer(out[:w * h * 3], np.uint8).reshape(h, w, 3)
        m = near(img, HUD_BG, 18)
        rows, cols = np.where(m)
        if len(rows) < w * h * 0.002:          # パネルにしては小さすぎる
            continue
        # 行・列ごとの密度を見て、いちばん濃い「ひと続きの範囲」を採る。
        # （背景に映り込んだPC画面のオーバーレイなど、離れた塊は拾わない）
        rh = np.bincount(rows, minlength=h)
        cw_ = np.bincount(cols, minlength=w)
        ry = longest_run(rh > rh.max() * 0.25)
        cx = longest_run(cw_ > cw_.max() * 0.25)
        if ry is None or cx is None or ry[1] - ry[0] < 10 or cx[1] - cx[0] < 10:
            continue
        boxes.append((cx[0], ry[0], cx[1] - cx[0] + 1, ry[1] - ry[0] + 1))
    if not boxes:
        return None
    b = np.median(np.array(boxes), axis=0).astype(int)
    pad = 12
    x0 = max(0, b[0] - pad); y0 = max(0, b[1] - pad)
    return (x0, y0, min(w - x0, b[2] + pad * 2), min(h - y0, b[3] + pad * 2))


def detect(path, crop, w, h, fps=FPS):
    """パネル内の「黄色の面積」「赤の面積」の増え方から、クリア／ミスの時刻を拾う。

    増えた面積が「マス1つ／丸1つ」ぶんに近いものだけを採用する。
    画面を横切る演出の帯は面積が桁違いに大きいので、これで除外できる。
    """
    gold, red = [], []
    for img in frames(path, fps, w, h, crop):
        gold.append(int(near(img, GOLD).sum()))
        red.append(int(near(img, RED).sum()))
    gold = np.array(gold, float)
    red = np.array(red, float)
    if len(gold) < 3:
        return [], gold, red

    # 表示は1920x1080基準で作られているので、パネルの高さから縮尺を出す
    k2 = (crop[3] / 248.0) ** 2                  # 面積の縮尺
    chip = 88 * 50 * k2                          # クリアのマス1つ
    dot = 3.14159 * 21 * 21 * k2                 # ミスの丸1つ

    def rises(sig, kind, area):
        # 3フレームの中央値で均してから、「1つぶん」に近い増加だけ拾う
        s = np.array([np.median(sig[max(0, i - 1):i + 2]) for i in range(len(sig))])
        d = np.diff(s)
        lo, hi = area * 0.35, area * 2.6
        out, last = [], -9
        for i, v in enumerate(d):
            t = (i + 1) / fps
            if lo <= v <= hi and t - last >= MIN_GAP:
                out.append((t, kind))
                last = t
        return out

    ev = rises(gold, "clear", chip) + rises(red, "miss", dot)
    ev.sort()
    # クリアとミスが同時に立った場合は、増えた量が大きい方を残す
    merged = []
    for t, k in ev:
        if merged and t - merged[-1][0] < MIN_GAP:
            continue
        merged.append((t, k))
    return merged, gold, red


def load_sfx(name, sr):
    """効果音をモノラルのfloat配列で読む（mp3が無ければwav）。"""
    src = SFX_DIR / f"{name}.mp3"
    if not src.exists():
        src = SFX_DIR / f"{name}.wav"
    tmp = HERE / f".{name}_{sr}.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", str(sr), str(tmp)])
    with wave.open(str(tmp)) as w:
        d = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    tmp.unlink(missing_ok=True)
    return d


def build_track(events, dur, sr, gain):
    track = np.zeros(int(dur * sr) + sr, np.float32)
    cache = {}
    for t, kind in events:
        name = "throw_clear" if kind == "clear" else "throw_miss"
        if name not in cache:
            cache[name] = load_sfx(name, sr)
        s = cache[name]
        i = int(t * sr)
        track[i:i + len(s)] += s * gain
    return np.clip(track, -1, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", help="書き出す動画（省略時は「元の名前_SE付き.mp4」）")
    ap.add_argument("--gain", type=float, default=0.9, help="効果音の音量（0〜1くらい）")
    ap.add_argument("--dry-run", action="store_true", help="検出結果だけ表示して終わる")
    ap.add_argument("--csv", help="検出結果をCSVに書き出す")
    a = ap.parse_args()

    src = Path(a.video).expanduser()
    w, h, dur = probe(src)
    print(f"動画: {src.name}  {w}x{h}  {dur:.1f}秒")

    crop = find_hud(src, dur, w, h)
    if not crop:
        sys.exit("種目表示（紺のパネル）が見つからなかった。オーバーレイが映っている動画か確認して。")
    print(f"種目表示の位置: x={crop[0]} y={crop[1]} w={crop[2]} h={crop[3]}")

    events, gold, red = detect(src, crop, w, h)
    print(f"検出: {len(events)}件")
    for t, k in events:
        print(f"  {t:7.2f}秒  {'クリア' if k == 'clear' else 'ミス'}")
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            cw = csv.writer(f)
            cw.writerow(["秒", "判定"])
            cw.writerows([[f"{t:.2f}", "クリア" if k == "clear" else "ミス"] for t, k in events])
        print(f"CSV: {a.csv}")
    if a.dry_run or not events:
        return

    sr = 48000
    track = build_track(events, dur, sr, a.gain)
    tmp = HERE / ".sfx_track.wav"
    with wave.open(str(tmp), "wb") as wv:
        wv.setnchannels(1); wv.setsampwidth(2); wv.setframerate(sr)
        wv.writeframes((track * 32767).astype(np.int16).tobytes())

    out = Path(a.out) if a.out else src.with_name(f"{src.stem}_SE付き.mp4")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-i", str(tmp),
         "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)])
    tmp.unlink(missing_ok=True)
    print(f"書き出し: {out}")


if __name__ == "__main__":
    main()
