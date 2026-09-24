#!/bin/bash
# 配信PCでこのフォルダをローカル配信する（効果音ラボのmp3を鳴らすとき用）。
# ダブルクリックで起動 → 表示されたURLをOBSのブラウザソースに貼る。閉じると止まる。
cd "$(dirname "$0")"
echo "操作パネル : http://localhost:8765/control.html"
echo "オーバーレイ: http://localhost:8765/overlay.html?room=ルーム名"
echo "（このウィンドウを閉じると止まります）"
python3 -m http.server 8765
