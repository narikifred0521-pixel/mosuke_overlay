#!/usr/bin/env python3
"""川西検定RTAの編集用ログ（kentei_control の「編集用CSVを保存」）から、
撮影した動画にマーカーを打った Final Cut Pro 用 FCPXML を作る。

各動画の撮影開始時刻（メタデータ）とログの時刻を突き合わせて、
1投ごと（○✕）・合格／不合格・★見せ場・級の切り替えを、その動画のその瞬間にマーカーとして置く。

使い方:
  python3 kentei_markers.py kentei_log_20261103_1530.csv A001.MOV A002.MOV ... -o 出力.fcpxml
  オプション:
    --offset 秒   動画の時計がスマホ（ログ）よりずれているとき。動画の時計が3秒進んでいれば --offset 3
    --end         メタデータの時刻が「録画の終わり」のカメラ用（開始＝その時刻−尺 にする）
    --name 名前   FCPのプロジェクト名
    --rough       粗編集モード：見せ場だけ等速で残し、ほかは早送り（下の「粗編集」）
    --speed 倍    早送りの速さ（既定 8倍）。--max-fast 秒 … 早送り1区間の長さの上限（既定 20秒。長い待ちはもっと速くなる）
    --drop        早送りせずに切り捨てる（等速の見せ場だけをつなぐ）
  動画は撮影順に並べてタイムラインに置く。ログの範囲に入らない動画もそのまま並べる（マーカーなし）。

粗編集（--rough）で等速のまま残すところ:
  合格した回の最後の3投／合格・ゴールのリアクション／不合格を決めた最後の1投／★見せ場の前後／級の始まり・やり直しの直後
  それ以外（不合格の回の途中、拾いに行く・並べ直す時間）は早送り（または --drop で切る）

マーカーの種類:
  ふつうのマーカー … 1投ごと（例「11級 1回目 3投目 ○ 2/7」）
  チャプターマーカー … スタート・級の始まり・やり直し・ゴール
  To Do マーカー（赤） … ★見せ場・不合格
"""
import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in j["streams"])
    fps = Fraction(v.get("r_frame_rate") or v.get("avg_frame_rate"))
    dur = float(j["format"].get("duration") or v.get("duration"))
    tags = {k.lower(): val for k, val in (j["format"].get("tags") or {}).items()}
    vtags = {k.lower(): val for k, val in (v.get("tags") or {}).items()}
    tc = vtags.get("timecode") or tags.get("timecode")
    if not tc:
        for s in j["streams"]:
            t = (s.get("tags") or {}).get("timecode")
            if t: tc = t; break
    created = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time") or vtags.get("creation_time")
    return {"fps": fps, "dur": dur, "w": int(v["width"]), "h": int(v["height"]), "tc": tc, "created": created, "audio": has_audio}


def parse_created(s):
    # iPhone: 2026-11-03T05:01:02+0900 ／ 他: 2026-11-03T20:01:02.000000Z（UTC）
    s = s.strip().replace("Z", "+00:00")
    if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone()  # Macのローカル時刻（日本時間）にそろえる


def tc_frames(tc, fps):
    if not tc:
        return 0
    parts = tc.replace(";", ":").split(":")
    h, m, s, f = (int(x) for x in parts)
    nominal = round(float(fps))
    return ((h * 60 + m) * 60 + s) * nominal + f


def rt(frames, fps):
    """フレーム数 → FCPXMLの有理数秒（"1001/30000s" 形式）"""
    fd = 1 / fps  # 1フレームの秒
    v = Fraction(frames) * fd
    return f"{v.numerator}/{v.denominator}s" if v.denominator != 1 else f"{v.numerator}s"


def load_log(path, day):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            hh, mm, rest = r["時刻"].split(":")
            ss, ms = (rest.split(".") + ["0"])[:2]
            t = day.replace(hour=int(hh), minute=int(mm), second=int(ss), microsecond=int(ms.ljust(3, "0")[:3]) * 1000)
            rows.append((t, r))
    # 日付をまたいだら（0時を過ぎたら）翌日にする
    for i in range(1, len(rows)):
        if rows[i][0] < rows[i - 1][0] - timedelta(hours=12):
            rows[i] = (rows[i][0] + timedelta(days=1), rows[i][1])
    return rows


def marker_xml(kind, r):
    g, tr, n, res, c = r["級"], r["回目"], r["投目"], r["結果"], r["成功数"]
    head = f"{g}級 {tr}回目" if g else ""
    if kind == "投擲":
        return "marker", f"{head} {n}投目 {res} {c}/7", None
    if kind == "合格":
        return "marker", f"★合格 {head}（経過 {r['経過']}）", None
    if kind == "不合格":
        return "todo", f"不合格 {head}（{c}/7）", None
    if kind == "ゴール":
        return "chapter", f"ゴール 全級クリア {r['経過']}", None
    if kind in ("スタート", "次の級へ", "やり直し"):
        return "chapter", f"{head} 開始" if kind != "スタート" else "スタート", None
    if kind == "★見せ場":
        return "todo", f"★見せ場 {head}", None
    if kind == "取り消し":
        return "marker", f"（取り消し {head}）", None
    if kind == "録画スタート":
        return "marker", "録画スタート（ログ）", None
    return "marker", f"{kind} {head}", None


def keep_windows(log, c_start, dur):
    """粗編集で等速のまま残す区間（動画の中の秒）を返す。重なりはまとめる"""
    # 挑戦ごと（級・回目）に投擲を集め、結果（合格／不合格）を付ける
    att = {}
    for t, r in log:
        key = (r["級"], r["回目"])
        a = att.setdefault(key, {"throws": [], "end": None, "res": None})
        if r["種類"] == "投擲":
            a["throws"].append(t)
        elif r["種類"] in ("合格", "ゴール", "不合格"):
            a["end"], a["res"] = t, r["種類"]
    sec = lambda t: (t - c_start).total_seconds()
    w = []
    for a in att.values():
        if a["res"] in ("合格", "ゴール"):
            for t in a["throws"][-3:]:
                w.append((sec(t) - 5, sec(t) + 3))          # 合格した回の最後の3投
            w.append((sec(a["end"]) - 2, sec(a["end"]) + 8))  # 合格のリアクション
        elif a["res"] == "不合格" and a["throws"]:
            w.append((sec(a["throws"][-1]) - 5, sec(a["end"]) + 6))  # 不合格を決めた最後の1投
    for t, r in log:
        if r["種類"] == "★見せ場":
            w.append((sec(t) - 10, sec(t) + 5))
        elif r["種類"] in ("スタート", "次の級へ", "やり直し"):
            w.append((sec(t) - 2, sec(t) + 10))
    w = sorted((max(0, x), min(dur, y)) for x, y in w if y > 0 and x < dur)
    out = []
    for x, y in w:
        if out and x <= out[-1][1] + 2:   # 2秒以内のすき間はつなげる
            out[-1] = (out[-1][0], max(out[-1][1], y))
        else:
            out.append((x, y))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--offset", type=float, default=0.0, help="動画の時計がログより何秒進んでいるか")
    ap.add_argument("--end", action="store_true", help="メタデータの時刻が録画の終わりのカメラ")
    ap.add_argument("--name", default="川西検定RTA_マーカー付き")
    ap.add_argument("--rough", action="store_true", help="見せ場だけ等速、ほかは早送りの粗編集を作る")
    ap.add_argument("--speed", type=float, default=8.0)
    ap.add_argument("--max-fast", type=float, default=20.0)
    ap.add_argument("--drop", action="store_true", help="早送りせずに切る")
    a = ap.parse_args()

    clips = []
    for p in a.videos:
        p = Path(p).expanduser().resolve()
        info = probe(p)
        if not info["created"]:
            sys.exit(f"撮影時刻が読めない: {p.name}（--offset では直せないので、ファイル名か別のカメラで確認して）")
        start = parse_created(info["created"])
        if a.end:
            start -= timedelta(seconds=info["dur"])
        start -= timedelta(seconds=a.offset)
        info.update(path=p, start=start)
        clips.append(info)
    clips.sort(key=lambda c: c["start"])

    log = load_log(a.csv, clips[0]["start"].replace(tzinfo=None))
    fps = clips[0]["fps"]
    fd = 1 / fps
    fd_s = f"{fd.numerator}/{fd.denominator}s"

    res, spine, report = [], [], []
    res.append(f'<format id="r1" name="FFVideoFormat{clips[0]["h"]}p{round(float(fps) * 100)}" frameDuration="{fd_s}" width="{clips[0]["w"]}" height="{clips[0]["h"]}"/>')
    offset_frames = 0
    total_markers = 0
    for i, c in enumerate(clips, start=2):
        rid = f"r{i}"
        frames = int(c["dur"] * float(c["fps"]))
        tc0 = tc_frames(c["tc"], c["fps"])
        src = "file://" + quote(str(c["path"]))
        res.append(f'<asset id="{rid}" name="{escape(c["path"].stem)}" start="{rt(tc0, fps)}" duration="{rt(frames, fps)}" hasVideo="1" '
                   f'hasAudio="{1 if c["audio"] else 0}" format="r1" audioSources="1" audioChannels="2">'
                   f'<media-rep kind="original-media" src="{escape(src)}"/></asset>')
        ms = []
        c_start = c["start"].replace(tzinfo=None)
        for t, r in log:
            sec = (t - c_start).total_seconds()
            if 0 <= sec < c["dur"]:
                kind, name, _ = marker_xml(r["種類"], r)
                f = tc0 + round(sec * float(fps))
                tag = {"chapter": "chapter-marker", "todo": "marker", "marker": "marker"}[kind]
                extra = ' completed="0"' if kind == "todo" else ""
                extra += f' posterOffset="0s"' if kind == "chapter" else ""
                ms.append(f'<{tag} start="{rt(f, fps)}" duration="{fd_s}" value="{escape(name)}"{extra}/>')
        total_markers += len(ms)
        if not a.rough:
            report.append(f'{c["path"].name}: 開始 {c["start"].strftime("%H:%M:%S")} 尺 {c["dur"] / 60:.1f}分 → マーカー {len(ms)}個')
            spine.append(f'<asset-clip ref="{rid}" offset="{rt(offset_frames, fps)}" name="{escape(c["path"].stem)}" start="{rt(tc0, fps)}" '
                         f'duration="{rt(frames, fps)}" format="r1" tcFormat="NDF">' + "".join(ms) + "</asset-clip>")
            offset_frames += frames
            continue

        # ── 粗編集：見せ場は等速、そのあいだは早送り（--drop なら切る） ──
        F = float(fps)
        keeps = keep_windows(log, c_start, c["dur"])
        segs, pos = [], 0.0
        for x, y in keeps:
            if x - pos > 1:
                segs.append(("fast", pos, x))
            segs.append(("keep", x, y))
            pos = y
        if c["dur"] - pos > 1:
            segs.append(("fast", pos, c["dur"]))
        kept = fast_out = 0.0
        for kind, x, y in segs:
            f0, f1 = round(x * F), round(y * F)
            if f1 <= f0:
                continue
            if kind == "keep":
                inside = [m for m in ms if f0 + tc0 <= int(Fraction(m.split('start="')[1].split('s"')[0]) / (1 / fps)) < f1 + tc0]
                spine.append(f'<asset-clip ref="{rid}" offset="{rt(offset_frames, fps)}" name="{escape(c["path"].stem)}" start="{rt(tc0 + f0, fps)}" '
                             f'duration="{rt(f1 - f0, fps)}" format="r1" tcFormat="NDF">' + "".join(inside) + "</asset-clip>")
                offset_frames += f1 - f0
                kept += (f1 - f0) / F
            elif not a.drop:
                n = f1 - f0
                k = max(a.speed, n / F / a.max_fast)   # 長い待ちは max-fast 秒に収まるまで速くする
                out_n = max(1, round(n / k))
                # timeMap：新しい時間（time）→ 元の時間（value）。クリップの始まり（tc0+f0）を基準に直線で速める
                tm = (f'<timeMap><timept time="{rt(tc0 + f0, fps)}" value="{rt(tc0 + f0, fps)}" interp="linear"/>'
                      f'<timept time="{rt(tc0 + f0 + out_n, fps)}" value="{rt(tc0 + f1, fps)}" interp="linear"/></timeMap>')
                spine.append(f'<asset-clip ref="{rid}" offset="{rt(offset_frames, fps)}" name="{escape(c["path"].stem)} 早送り×{k:.0f}" '
                             f'start="{rt(tc0 + f0, fps)}" duration="{rt(out_n, fps)}" format="r1" tcFormat="NDF">{tm}'
                             f'<adjust-volume amount="-96dB"/></asset-clip>')
                offset_frames += out_n
                fast_out += out_n / F
        report.append(f'{c["path"].name}: {c["dur"] / 60:.1f}分 → 等速 {kept / 60:.1f}分＋早送り {fast_out / 60:.1f}分')

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10">\n<resources>\n' + "\n".join(res) +
           f'\n</resources>\n<library>\n<event name="{escape(a.name)}">\n<project name="{escape(a.name)}">\n'
           f'<sequence format="r1" duration="{rt(offset_frames, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n<spine>\n'
           + "\n".join(spine) + "\n</spine>\n</sequence>\n</project>\n</event>\n</library>\n</fcpxml>\n")
    Path(a.out).write_text(xml, encoding="utf-8")
    print("\n".join(report))
    print(f"ログ {len(log)}行のうち、マーカーにしたもの {total_markers}個 → {a.out}")
    if a.rough:
        print(f"粗編集の長さ: {offset_frames / float(fps) / 60:.1f}分（早送りは無音。FCPでの速さの読み込みは要確認）")
    if total_markers == 0:
        print("⚠ マーカーが1つも入らなかった。動画とスマホの時計のずれ（--offset）か、録画の終わりの時刻を持つカメラ（--end）を確認して")


if __name__ == "__main__":
    main()
