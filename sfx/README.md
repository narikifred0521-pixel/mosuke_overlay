# 効果音について

このフォルダには2種類ある。

- `*.wav` … `make_sfx.py` で合成したもの。自由に配布できるので、GitHubに置いてある
- `*.mp3` … [効果音ラボ](https://soundeffect-lab.info/) の素材。**素材そのものの再配布が禁止**なので、Gitには入れていない（`.gitignore` で除外）

オーバーレイは **mp3があればmp3を、無ければwavを** 鳴らす。
配信PCで効果音ラボの音を使うには、このフォルダにmp3を入れてローカルで動かす（`start_local.command`）。

| ファイル名 | 鳴るとき | 効果音ラボの素材 |
| --- | --- | --- |
| throw_clear | 1投クリア | 剣で斬る1 |
| throw_miss | 1投ミス | 刀の素振り（ピュッ） |
| clear | 種目クリア | 和太鼓でドン |
| stage | ステージ突破 | 和太鼓でドドン |
| complete | 完全制覇 | 歓声と拍手1 |
| miss | 敗退 | ショック1 衝撃の一瞬 |
| over | FINALの失格・TIME UP | お寺の鐘 ゴーン |
| lastchance | ラストチャンス突入 | 和太鼓でカカッ |
| start | FINALスタート | （合成音のみ） |
| tick / tick_last | 残り10秒のカウント | （合成音のみ） |
