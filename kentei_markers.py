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
  動画は撮影順に並べてタイムラインに置く。ログの範囲に入らない動画もそのまま並べる（マーカーなし）。

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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--offset", type=float, default=0.0, help="動画の時計がログより何秒進んでいるか")
    ap.add_argument("--end", action="store_true", help="メタデータの時刻が録画の終わりのカメラ")
    ap.add_argument("--name", default="川西検定RTA_マーカー付き")
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
        report.append(f'{c["path"].name}: 開始 {c["start"].strftime("%H:%M:%S")} 尺 {c["dur"] / 60:.1f}分 → マーカー {len(ms)}個')
        spine.append(f'<asset-clip ref="{rid}" offset="{rt(offset_frames, fps)}" name="{escape(c["path"].stem)}" start="{rt(tc0, fps)}" '
                     f'duration="{rt(frames, fps)}" format="r1" tcFormat="NDF">' + "".join(ms) + "</asset-clip>")
        offset_frames += frames

    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10">\n<resources>\n' + "\n".join(res) +
           f'\n</resources>\n<library>\n<event name="{escape(a.name)}">\n<project name="{escape(a.name)}">\n'
           f'<sequence format="r1" duration="{rt(offset_frames, fps)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n<spine>\n'
           + "\n".join(spine) + "\n</spine>\n</sequence>\n</project>\n</event>\n</library>\n</fcpxml>\n")
    Path(a.out).write_text(xml, encoding="utf-8")
    print("\n".join(report))
    print(f"ログ {len(log)}行のうち、マーカーにしたもの {total_markers}個 → {a.out}")
    if total_markers == 0:
        print("⚠ マーカーが1つも入らなかった。動画とスマホの時計のずれ（--offset）か、録画の終わりの時刻を持つカメラ（--end）を確認して")


if __name__ == "__main__":
    main()
