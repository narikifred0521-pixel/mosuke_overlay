"""オーバーレイの効果音（sfx/*.wav）を作る。標準ライブラリだけで合成する。

  python3 make_sfx.py

音を差し替えたいときは、同じファイル名のwavを sfx/ に置けばそのまま使われる。
"""
import math
import struct
import wave
from pathlib import Path

SR = 44100
OUT = Path(__file__).parent / "sfx"


def env(i, n, attack=0.005, decay=0.9, sustain=0.0, release=0.2):
    """0..1 の音量カーブ（かんたんなADSR）。"""
    t = i / SR
    total = n / SR
    a = attack * total if attack < 1 else attack
    if t < a:
        return t / a
    rel = release * total
    if t > total - rel:
        return max(0.0, (total - t) / rel) * (sustain if sustain else 1.0) * 0.999
    d = decay * total
    if t < d:
        k = (t - a) / max(1e-6, d - a)
        return (1 - k) * (1 - sustain) + sustain
    return sustain if sustain else 0.4


def tone(freq, dur, harmonics=(1, 0.35, 0.18, 0.08), vib=0.0, **kw):
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        f = freq * (1 + vib * math.sin(2 * math.pi * 5.5 * t))
        s = sum(a * math.sin(2 * math.pi * f * (h + 1) * t) for h, a in enumerate(harmonics))
        out.append(s * env(i, n, **kw))
    return out


def square(freq, dur, **kw):
    n = int(SR * dur)
    return [(1 if math.sin(2 * math.pi * freq * i / SR) > 0 else -1) * 0.5 * env(i, n, **kw) for i in range(n)]


def noise(dur, decay=0.5):
    n = int(SR * dur)
    x, out = 12345, []
    for i in range(n):
        x = (1103515245 * x + 12345) % (1 << 31)
        out.append(((x / (1 << 30)) - 1) * math.exp(-i / SR / decay))
    return out


def mix(*layers):
    """(サンプル列, 開始秒, 音量) を重ねる。"""
    n = max(int(start * SR) + len(buf) for buf, start, _ in layers)
    out = [0.0] * n
    for buf, start, gain in layers:
        off = int(start * SR)
        for i, v in enumerate(buf):
            out[off + i] += v * gain
    return out


def save(name, samples, peak=0.85):
    m = max(1e-9, max(abs(v) for v in samples))
    k = peak / m
    data = b"".join(struct.pack("<h", int(max(-1, min(1, v * k)) * 32767)) for v in samples)
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)
    print(f"{name}  {len(samples) / SR:.2f}s  {len(data) // 1024}KB")


# 音階（Hz）
A4, CS5, E5, A5, CS6, E6, B4, D5, FS5 = 440, 554.37, 659.25, 880, 1108.73, 1318.51, 493.88, 587.33, 739.99

# クリア: 明るいベルの3音
save("clear.wav", mix(
    (tone(A5, 0.5, (1, 0.5, 0.25, 0.12), decay=0.8), 0.00, 1.0),
    (tone(CS6, 0.5, (1, 0.5, 0.25, 0.12), decay=0.8), 0.07, 0.9),
    (tone(E6, 0.8, (1, 0.4, 0.2, 0.1), decay=0.9), 0.14, 0.9),
    (noise(0.25, 0.08), 0.00, 0.15),
))

# ミス: 低いブザー2発
save("miss.wav", mix(
    (square(146.83, 0.22, decay=0.7), 0.00, 1.0),
    (square(110.00, 0.38, decay=0.8), 0.24, 1.0),
    (noise(0.12, 0.05), 0.00, 0.2),
))

# ステージクリア: ファンファーレ
save("stage.wav", mix(
    (tone(A4, 0.22, (1, 0.6, 0.4, 0.2), decay=0.9), 0.00, 0.9),
    (tone(E5, 0.22, (1, 0.6, 0.4, 0.2), decay=0.9), 0.18, 0.9),
    (tone(A5, 1.30, (1, 0.7, 0.45, 0.25, 0.12), vib=0.004, attack=0.01, decay=0.25, sustain=0.55, release=0.45), 0.36, 1.0),
    (tone(CS6, 1.30, (1, 0.5, 0.3, 0.15), vib=0.004, attack=0.02, decay=0.25, sustain=0.45, release=0.45), 0.36, 0.55),
    (noise(0.5, 0.18), 0.30, 0.18),
))

# 完全制覇: 長めのファンファーレ
save("complete.wav", mix(
    (tone(A4, 0.20, (1, 0.6, 0.4, 0.2), decay=0.9), 0.00, 0.8),
    (tone(CS5, 0.20, (1, 0.6, 0.4, 0.2), decay=0.9), 0.16, 0.8),
    (tone(E5, 0.20, (1, 0.6, 0.4, 0.2), decay=0.9), 0.32, 0.9),
    (tone(A5, 2.20, (1, 0.7, 0.5, 0.3, 0.15), vib=0.005, attack=0.01, decay=0.2, sustain=0.6, release=0.4), 0.48, 1.0),
    (tone(E5, 2.20, (1, 0.5, 0.3, 0.15), vib=0.005, attack=0.02, decay=0.2, sustain=0.5, release=0.4), 0.48, 0.6),
    (tone(CS6, 2.00, (1, 0.4, 0.2), vib=0.005, attack=0.05, decay=0.2, sustain=0.4, release=0.4), 0.60, 0.45),
    (noise(0.8, 0.25), 0.42, 0.2),
))

# タイムオーバー・失格: 下がるブザー
save("over.wav", mix(
    (square(196.00, 0.30, decay=0.8), 0.00, 1.0),
    (square(155.56, 0.30, decay=0.8), 0.28, 1.0),
    (square(116.54, 0.70, decay=0.9), 0.56, 1.0),
))

# FINALスタート
save("start.wav", mix(
    (tone(FS5, 0.18, (1, 0.5, 0.3), decay=0.8), 0.00, 1.0),
    (tone(B4, 0.35, (1, 0.5, 0.3), decay=0.85), 0.16, 1.0),
    (noise(0.2, 0.06), 0.00, 0.25),
))

# 残り10秒のカウント音（最後の1秒だけ高く）
save("tick.wav", tone(D5, 0.10, (1, 0.3), decay=0.6))
save("tick_last.wav", tone(A5, 0.16, (1, 0.4, 0.2), decay=0.7))
