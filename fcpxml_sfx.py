"""Final Cut ProのFCPXMLに、1投ごとの効果音を自動で入れる。

動画に映っているオーバーレイの表示（クリアの黄色いマス／ミスの赤い丸）が増えた瞬間を読み取り、
その時刻に効果音クリップをレーン-1（映像の下の音声レーン）へ並べたFCPXMLを書き出す。
スマホ配信だと効果音がマイク越しにしか入らないので、編集で綺麗に載せ直すためのもの。

  python3 fcpxml_sfx.py 入力.fcpxml                    # 入力_SE.fcpxml を書き出す
  python3 fcpxml_sfx.py 入力.fcpxmld --dry-run         # 検出した時刻の一覧だけ出す
  python3 fcpxml_sfx.py 入力.fcpxml --video 別の動画.mov --csv 結果.csv

必要なもの: ffmpeg / ffprobe / numpy
"""
import argparse
import csv
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from video_sfx import detect, find_hud, probe

HERE = Path(__file__).parent
SFX_DIR = HERE / "sfx"
DOCTYPE = "<!DOCTYPE fcpxml>"
SFX_FOR = {"clear": "throw_clear", "miss": "throw_miss"}


class SfxError(Exception):
    pass


def parse_time(v, default=Fraction(0)):
    if not v:
        return default
    s = v.strip().rstrip("s")
    return Fraction(*[int(x) for x in s.split("/")]) if "/" in s else Fraction(s)


def fmt_time(v):
    v = Fraction(v).limit_denominator(1_000_000_000)
    return f"{v.numerator}s" if v.denominator == 1 else f"{v.numerator}/{v.denominator}s"


def media_path(asset, base):
    """<asset>から動画ファイルのパスを取り出す（media-rep形式とsrc属性形式の両方に対応）。"""
    rep = asset.find("media-rep")
    src = rep.get("src") if rep is not None else asset.get("src")
    if not src:
        return None
    if src.startswith("file://"):
        return Path(unquote(urlparse(src).path))
    p = Path(unquote(src))
    return p if p.is_absolute() else (base / p)


def sfx_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                         check=True, capture_output=True).stdout.decode().strip()
    return Fraction(out).limit_denominator(1000)


def add_sfx_assets(resources, use_media_rep):
    """効果音をリソースに登録して、種類→(id, 長さ) を返す。"""
    ids = {}
    for kind, name in SFX_FOR.items():
        path = SFX_DIR / f"{name}.mp3"
        if not path.exists():
            path = SFX_DIR / f"{name}.wav"
        if not path.exists():
            raise SfxError(f"効果音が見つかりません: {path}")
        dur = sfx_duration(path)
        aid = f"r_sfx_{name}"
        if resources.find(f"./asset[@id='{aid}']") is None:
            url = "file://" + quote(str(path.resolve()))
            attrib = {"id": aid, "name": name, "start": "0s", "duration": fmt_time(dur),
                      "hasAudio": "1", "audioSources": "1", "audioChannels": "1", "audioRate": "44100"}
            if not use_media_rep:
                attrib["src"] = url
            asset = ET.SubElement(resources, "asset", attrib=attrib)
            if use_media_rep:
                ET.SubElement(asset, "media-rep", attrib={"kind": "original-media", "src": url})
        ids[kind] = (aid, dur)
    return ids


def snapper(root, resources):
    """シーケンスのフレーム間隔に合わせて時刻を丸める関数を返す（FCPは半端な時刻を嫌う）。"""
    seq = root.find(".//sequence")
    fd = None
    if seq is not None:
        fmt = resources.find(f"./format[@id='{seq.get('format')}']")
        if fmt is not None and fmt.get("frameDuration"):
            fd = parse_time(fmt.get("frameDuration"))
    if not fd:
        fd = Fraction(1, 30)
    return lambda t: Fraction(round(Fraction(t) / fd)) * fd


def insert_into_clip(clip, events, ids, seen, snap):
    """1つのasset-clipに、その範囲に入る効果音クリップを差し込む。"""
    start = parse_time(clip.get("start"))
    dur = parse_time(clip.get("duration"), None)
    end = start + dur if dur else None
    # DTD上、markerは他の子要素より後ろでなければならないので、先頭から順に差し込む
    pos = 0
    n = 0
    for t, kind in events:
        tt = snap(t)
        if tt < start or (end is not None and tt >= end):
            continue
        if (id(clip), t) in seen:
            continue
        seen.add((id(clip), t))
        aid, sdur = ids[kind]
        sdur = snap(sdur) or snap(0.1)
        el = ET.Element("asset-clip", attrib={
            "ref": aid, "lane": "-1", "offset": fmt_time(tt), "start": "0s",
            "duration": fmt_time(sdur), "name": f"SE_{SFX_FOR[kind]}", "audioRole": "effects",
        })
        clip.insert(pos, el)
        pos += 1
        n += 1
    return n


def read_csv_events(path):
    """CSV（1列目=秒、2列目=クリア/ミス）を読む。押し忘れは行を足す、余計なら行を消す。"""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if not row or not row[0].strip():
                continue
            try:
                t = float(row[0])
            except ValueError:
                continue  # 見出し行
            kind = "miss" if len(row) > 1 and "ミス" in row[1] else "clear"
            out.append((t, kind))
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fcpxml", help="入力FCPXML（.fcpxmld のフォルダでもよい）")
    ap.add_argument("--video", help="解析する動画（省略時はFCPXMLから自動で解決）")
    ap.add_argument("--out", help="出力FCPXML（省略時は「元の名前_SE.fcpxml」）")
    ap.add_argument("--csv", help="検出結果をCSVに書き出す")
    ap.add_argument("--dry-run", action="store_true", help="検出結果だけ表示して終わる")
    ap.add_argument("--from-csv", help="映像を解析せず、このCSV（秒,判定）の通りに効果音を入れる。押し忘れの修正用")
    ap.add_argument("--offset", type=float, default=0.0, help="全部の効果音を前後にずらす秒数（例: -0.2）")
    a = ap.parse_args()

    src = Path(a.fcpxml).expanduser()
    if src.is_dir() and src.suffix == ".fcpxmld":
        src = src / "Info.fcpxml"
    if not src.exists():
        sys.exit(f"入力ファイルが見つかりません: {src}")

    tree = ET.parse(src)
    root = tree.getroot()
    if root.tag != "fcpxml":
        sys.exit(f"ルート要素が<fcpxml>ではありません: <{root.tag}>")
    resources = root.find("resources")
    spine = root.find(".//spine")
    if resources is None or spine is None:
        sys.exit("<resources>または<spine>が見つかりません。")

    clips = spine.findall("asset-clip") + spine.findall(".//clip/asset-clip")
    if not clips:
        sys.exit("<spine>にasset-clipがありません。")

    # 解析する動画を決める（--video 優先、無ければ最初のasset-clipの参照先）
    if a.video:
        video = Path(a.video).expanduser()
    else:
        ref = clips[0].get("ref")
        asset = resources.find(f"./asset[@id='{ref}']")
        if asset is None:
            sys.exit(f"asset id={ref} が見つかりません。--video で動画を指定して。")
        video = media_path(asset, src.parent)
    if not video or not video.exists():
        sys.exit(f"動画ファイルが見つかりません: {video}\n--video で場所を指定して。")

    if a.from_csv:
        events = read_csv_events(Path(a.from_csv).expanduser())
        print(f"CSVから読み込み: {a.from_csv}")
    else:
        w, h, dur = probe(video)
        print(f"動画: {video.name}  {w}x{h}  {dur:.1f}秒")
        crop = find_hud(video, dur, w, h)
        if not crop:
            sys.exit("種目表示（紺のパネル）が見つからなかった。オーバーレイが映っている動画か確認して。")
        events, _, _ = detect(video, crop, w, h)
    if a.offset:
        events = [(max(0.0, t + a.offset), k) for t, k in events]
    print(f"検出: {len(events)}件（クリア{sum(1 for _, k in events if k == 'clear')} / "
          f"ミス{sum(1 for _, k in events if k == 'miss')}）")
    for t, k in events:
        print(f"  {t:7.2f}秒  {'クリア' if k == 'clear' else 'ミス'}")

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            cw = csv.writer(f)
            cw.writerow(["秒", "判定", "効果音"])
            cw.writerows([[f"{t:.2f}", "クリア" if k == "clear" else "ミス", SFX_FOR[k]] for t, k in events])
        print(f"CSV: {a.csv}")

    if a.dry_run or not events:
        return

    use_media_rep = resources.find("./asset/media-rep") is not None
    ids = add_sfx_assets(resources, use_media_rep)
    seen = set()
    snap = snapper(root, resources)
    total = sum(insert_into_clip(c, events, ids, seen, snap) for c in clips)
    print(f"挿入: {total}件（レーン-1・ロール=エフェクト）")

    out = Path(a.out) if a.out else src.with_name(f"{src.stem}_SE.fcpxml")
    ET.indent(root, space="    ")
    with open(out, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(DOCTYPE.encode() + b"\n")
        ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=False)
    print(f"書き出し: {out}")
    print("Final Cut Proの「ファイル > 読み込む > XML…」で読み込む。")


if __name__ == "__main__":
    main()
