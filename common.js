// MöSUKE 配信オーバーレイ 共通：大会データ・状態・同期
// control.html（操作）→ overlay.html（OBSブラウザソース）へ状態を送る。
// 同期は BroadcastChannel + localStorage（同じブラウザ／OBSのカスタムドック同士で動く）。
// スマホ操作にするときは Firebase を足す（もるまさスコアと同じ方式）。

const STAGES = [
  { key: "1", label: "1st Stage", short: "1st" },
  { key: "2", label: "2nd Stage", short: "2nd" },
  { key: "3", label: "3rd Stage", short: "3rd" },
  { key: "F", label: "FINAL STAGE", short: "FINAL" },
];

// steps = クリアしていく順番のラベル（数＝必要クリア数）、miss = 許されるミス数
const EVENTS = [
  { id: "1-1", stage: "1", name: "ステップバイステップ", kind: "順手", steps: ["4m", "6m", "8m"], miss: 2 },
  { id: "1-2", stage: "1", name: "ウッドボーン", kind: "縦", steps: ["3.5m", "4m", "4.5m"], miss: 2 },
  { id: "1-3", stage: "1", name: "スローアンドジェントル", kind: "手前取り", steps: ["4m", "4.5m", "5m"], miss: 2 },
  { id: "1-4", stage: "1", name: "パワークラッシュ", kind: "飛ばし", steps: ["4→8m", "5→9m", "6→10m"], miss: 2 },
  { id: "1-5", stage: "1", name: "そりたつモル棒", kind: "ふわり", steps: ["1回"], miss: 1 },
  { id: "2-1", stage: "2", name: "ヘルトライアングル", kind: "縦ふわり系", steps: ["1回"], miss: 2 },
  { id: "2-2", stage: "2", name: "ナッシングハップン", kind: "その場取り", steps: ["1回"], miss: 2 },
  { id: "2-3", stage: "2", name: "オーバーザウォール", kind: "束裏飛ばし", steps: ["1回"], miss: 2 },
  { id: "2-4", stage: "2", name: "プレッシャーストレート", kind: "遠投系", steps: ["1回"], miss: 2 },
  { id: "3-1", stage: "3", name: "デビルフック", kind: "曲げ系", steps: ["左", "右"], miss: 1 },
  { id: "3-2", stage: "3", name: "デスエンド", kind: "12m遠投", steps: ["1回"], miss: 1 },
  { id: "3-3", stage: "3", name: "クレイジータイニーウッド", kind: "ガチ端引っ掛け", steps: ["左", "右"], miss: 1 },
  { id: "3-4", stage: "3", name: "キャッチザレインボー", kind: "7mふわり", steps: ["1回"], miss: 1 },
  { id: "F", stage: "F", name: "タイムアタック50", kind: "1分10秒以内", final: true },
];

const FINAL_LIMIT_MS = 70 * 1000;
const FINAL_GOAL = 50;

const PLAYERS = [
  { no: 1, name: "渡辺達也", title: "森下一派" },
  { no: 2, name: "なぎ", title: "なぎちゃんず／ALLINマネージャー" },
  { no: 3, name: "ゆうやん", title: "初代木龍／JO2023優勝" },
  { no: 4, name: "石田麻美", title: "" },
  { no: 5, name: "石田隼也", title: "JO2024優勝／7出し公式記録保持者" },
  { no: 6, name: "木下優樹", title: "キング" },
  { no: 7, name: "田中凱也", title: "JO2026準優勝／象使い" },
  { no: 8, name: "柿沼智文", title: "SASUKEインフルエンサー／世界大会2026準優勝" },
  { no: 9, name: "ひできち", title: "選手権予選関東地区優勝" },
  { no: 10, name: "古田優弥", title: "スキルチャレンジ世界2位／モルック研究家" },
  { no: 11, name: "松原翔平", title: "2024年日本代表／JO2024優勝／Mr.MöSUKE" },
  { no: 12, name: "横山航大", title: "JO2026優勝／靴のモルタ勤務／モルクール指導員／モスケ君" },
];

// ── 状態 ─────────────────────────────────────────
// S.rec[no][eventId] = { log: ["c","m",...] }  … 投擲ごとの記録（取り消しはpop）
// S.fin[no] = { start, stop, score, streak, log: [点数...], dq: "" }
const STORE_KEY = "mosuke_overlay_state_v1";

function blankState() {
  return {
    player: 1,
    event: "1-1",
    show: { hud: true, player: true, progress: true, board: false },
    rec: {},
    fin: {},
    fx: null, // { type: "clear"|"fail"|"stage"|"allclear"|"final", text, t }
    t: Date.now(),
  };
}

function loadState() {
  try {
    const s = JSON.parse(localStorage.getItem(STORE_KEY));
    if (s && s.rec) return Object.assign(blankState(), s);
  } catch (e) {}
  return blankState();
}

const chan = "BroadcastChannel" in window ? new BroadcastChannel("mosuke_overlay") : null;

function saveState(S) {
  S.t = Date.now();
  try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch (e) {}
  if (chan) chan.postMessage(S);
}

function onState(cb) {
  if (chan) chan.onmessage = (e) => cb(e.data);
  window.addEventListener("storage", (e) => {
    if (e.key === STORE_KEY && e.newValue) cb(JSON.parse(e.newValue));
  });
}

// ── 判定 ─────────────────────────────────────────
const evById = (id) => EVENTS.find((e) => e.id === id);
const playerByNo = (no) => PLAYERS.find((p) => p.no === no);

function evLog(S, no, id) {
  return (((S.rec[no] || {})[id]) || { log: [] }).log;
}

// 種目の状況: { clears, misses, status: "todo"|"live"|"clear"|"fail" }
function evStatus(S, no, id) {
  const ev = evById(id);
  if (ev.final) return finStatus(S, no);
  const log = evLog(S, no, id);
  const clears = log.filter((x) => x === "c").length;
  const misses = log.filter((x) => x === "m").length;
  let status = log.length ? "live" : "todo";
  if (clears >= ev.steps.length) status = "clear";
  else if (misses > ev.miss) status = "fail";
  return { clears, misses, status };
}

function finState(S, no) {
  return S.fin[no] || { start: 0, stop: 0, score: 0, streak: 0, log: [], dq: "" };
}

function finElapsed(f, now = Date.now()) {
  if (!f.start) return 0;
  return (f.stop || now) - f.start;
}

function finStatus(S, no) {
  const f = finState(S, no);
  let status = "todo";
  if (f.start) status = "live";
  if (f.dq) status = "fail";
  else if (f.stop) status = finElapsed(f) <= FINAL_LIMIT_MS && f.score === FINAL_GOAL ? "clear" : "fail";
  return { status, clears: 0, misses: f.streak };
}

// その選手がどこまで行ったか: { reached: "1"|"2"|"3"|"F"|"ALL", out: bool, label }
function playerProgress(S, no) {
  for (const st of STAGES) {
    const evs = EVENTS.filter((e) => e.stage === st.key);
    const sts = evs.map((e) => evStatus(S, no, e.id).status);
    if (sts.includes("fail")) return { reached: st.key, out: true, label: `${st.short} 敗退` };
    if (!sts.every((x) => x === "clear")) {
      const started = sts.some((x) => x !== "todo");
      return { reached: st.key, out: false, label: started ? `${st.short} 挑戦中` : st.key === "1" ? "未挑戦" : `${st.short} 進出` };
    }
  }
  return { reached: "ALL", out: false, label: "完全制覇" };
}

function stageCleared(S, no, stageKey) {
  return EVENTS.filter((e) => e.stage === stageKey).every((e) => evStatus(S, no, e.id).status === "clear");
}

function fmtTime(ms) {
  const s = Math.max(0, ms) / 1000;
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${m}:${sec.toFixed(2).padStart(5, "0")}`;
}
