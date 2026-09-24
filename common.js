// MöSUKE 配信オーバーレイ 共通：大会データ・状態・同期
// control.html（操作）→ overlay.html（OBSブラウザソース）へ状態を送る。
// 同期は BroadcastChannel + localStorage（同じブラウザ／OBSのカスタムドック同士で動く）。
// ルーム名を設定すると Firebase Realtime DB でも同期する（スマホ操作・別PC用。もるまさスコアと同じDB）。
//   操作パネル: 設定タブ「スマホ同期」でルーム名を入れる / オーバーレイ: overlay.html?room=ルーム名

const STAGES = [
  { key: "1", label: "1st Stage", short: "1st" },
  { key: "2", label: "2nd Stage", short: "2nd" },
  { key: "3", label: "3rd Stage", short: "3rd" },
  { key: "F", label: "FINAL STAGE", short: "FINAL" },
];

// steps = クリアしていく順番のラベル（数＝必要クリア数）、miss = 許されるミス数
let EVENTS = [
  { id: "1-1", stage: "1", name: "ステップバイステップ", kind: "順手", steps: ["4m", "6m", "8m"], miss: 3 },
  { id: "1-2", stage: "1", name: "ウッドボーン", kind: "縦", steps: ["3.5m", "4m", "4.5m"], miss: 3 },
  { id: "1-3", stage: "1", name: "スローアンドジェントル", kind: "手前取り", steps: ["4m", "4.5m", "5m"], miss: 3 },
  { id: "1-4", stage: "1", name: "パワークラッシュ", kind: "飛ばし", steps: ["4→8m", "5→9m", "6→10m"], miss: 3 },
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

let FINAL_LIMIT_MS = 70 * 1000;
let FINAL_GOAL = 50;
let FINAL_BURST = 25;   // 目標を超えたら戻る点数
let FINAL_MISS_DQ = 3;  // この回数連続ミスで失格
let LAYOUT = { hud: "br" }; // 種目HUDの位置: br=右下 / tl=左上
let SFX = { on: true, vol: 0.8 };  // 効果音（鳴らすのはオーバーレイ側だけ）

let PLAYERS = [
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

// ── 設定（操作パネルの「設定」タブで編集。上の値が初期値） ──────────
const CFG_KEY = "mosuke_overlay_config_v1";
const DEFAULT_EVENTS = JSON.parse(JSON.stringify(EVENTS));
const DEFAULT_PLAYERS = JSON.parse(JSON.stringify(PLAYERS));

function defaultConfig() {
  return {
    players: JSON.parse(JSON.stringify(DEFAULT_PLAYERS)),
    events: Object.fromEntries(DEFAULT_EVENTS.filter((e) => !e.final).map((e) => [e.id, { name: e.name, steps: e.steps, miss: e.miss }])),
    final: { limitSec: 70, goal: 50, burst: 25, missDq: 3 },
    sfx: { on: true, vol: 0.8 },
    layout: { hud: "br" },
  };
}

function loadConfig() {
  const c = defaultConfig();
  try {
    const s = JSON.parse(localStorage.getItem(CFG_KEY));
    if (s) {
      if (Array.isArray(s.players)) c.players = s.players;
      if (s.events) for (const id in c.events) Object.assign(c.events[id], s.events[id] || {});
      Object.assign(c.final, s.final || {});
      Object.assign(c.layout, s.layout || {});
      Object.assign(c.sfx, s.sfx || {});
    }
  } catch (e) {}
  return c;
}

function applyConfig(c) {
  PLAYERS = c.players.slice().sort((a, b) => a.no - b.no);
  EVENTS = DEFAULT_EVENTS.map((e) => (e.final ? Object.assign({}, e) : Object.assign({}, e, c.events[e.id])));
  FINAL_LIMIT_MS = c.final.limitSec * 1000;
  FINAL_GOAL = c.final.goal;
  FINAL_BURST = c.final.burst;
  FINAL_MISS_DQ = c.final.missDq;
  const fe = EVENTS.find((e) => e.final);
  fe.name = `タイムアタック${FINAL_GOAL}`;
  fe.kind = `${fmtLimit(c.final.limitSec)}以内`;
  LAYOUT = c.layout;
  SFX = c.sfx;
}

function fmtLimit(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? `${m}分${s ? s + "秒" : ""}` : `${s}秒`;
}

const cfgChan = "BroadcastChannel" in window ? new BroadcastChannel("mosuke_overlay_cfg") : null;

function saveConfig(c) {
  try { localStorage.setItem(CFG_KEY, JSON.stringify(c)); } catch (e) {}
  if (cfgChan) cfgChan.postMessage(1);
  fbWrite("config", c);
}

// 設定が変わったら読み込み直す（オーバーレイ側）
function onConfig(cb) {
  if (cfgChan) cfgChan.onmessage = cb;
  window.addEventListener("storage", (e) => { if (e.key === CFG_KEY) cb(); });
  fbListen("config", (c) => {
    const txt = JSON.stringify(c);
    if (txt === localStorage.getItem(CFG_KEY)) return; // 自分の書き込み・同じ内容なら何もしない
    try { localStorage.setItem(CFG_KEY, txt); } catch (e) {}
    cb();
  });
}

// ── Firebase 同期（ルーム名があるときだけ） ──────────────
const FB_URL = "https://morumasa-score-4818b-default-rtdb.asia-southeast1.firebasedatabase.app";
const ROOM_KEY = "mosuke_overlay_room";
const ROOM = (new URLSearchParams(location.search).get("room") || (() => { try { return localStorage.getItem(ROOM_KEY); } catch (e) { return ""; } })() || "")
  .replace(/[^\w-]/g, "");
let fbDb = null;
let fbStatus = ROOM ? "接続中…" : "オフ";
const fbStatusCbs = [];
function setFbStatus(t) { fbStatus = t; fbStatusCbs.forEach((f) => f(t)); }

if (ROOM && window.firebase) {
  try {
    firebase.initializeApp({ databaseURL: FB_URL });
    fbDb = firebase.database();
    fbDb.ref(".info/connected").on("value", (s) => setFbStatus(s.val() ? "接続OK" : "接続中…"));
  } catch (e) { setFbStatus("エラー"); }
}

function fbWrite(kind, data) {
  if (!fbDb) return;
  fbDb.ref(`mosuke_overlay/${ROOM}/${kind}`).set(JSON.parse(JSON.stringify(data)))
    .catch(() => setFbStatus("書き込み不可（DBのルール未設定）"));
}

function fbListen(kind, cb) {
  if (!fbDb) return;
  fbDb.ref(`mosuke_overlay/${ROOM}/${kind}`).on("value", (s) => { if (s.val()) cb(s.val()); },
    () => setFbStatus("読み込み不可（DBのルール未設定）"));
}

applyConfig(loadConfig());

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

// Firebase は空の配列・オブジェクトを消し、数字キーを配列にするので、受け取ったら形を整える
function normalizeState(s) {
  s = Object.assign(blankState(), s);
  s.show = Object.assign(blankState().show, s.show);
  const obj = (x) => (x ? Object.assign({}, x) : {});
  s.rec = obj(s.rec); s.fin = obj(s.fin);
  for (const no in s.rec) {
    if (!s.rec[no]) { delete s.rec[no]; continue; }
    s.rec[no] = obj(s.rec[no]);
    for (const id in s.rec[no]) s.rec[no][id] = { log: (s.rec[no][id] && s.rec[no][id].log) || [] };
  }
  for (const no in s.fin) {
    if (!s.fin[no]) { delete s.fin[no]; continue; }
    s.fin[no] = Object.assign({ start: 0, stop: 0, score: 0, streak: 0, log: [], dq: "" }, s.fin[no]);
  }
  return s;
}

function loadState() {
  try {
    const s = JSON.parse(localStorage.getItem(STORE_KEY));
    if (s) { lastStateT = s.t || 0; return normalizeState(s); }
  } catch (e) {}
  return blankState();
}

const chan = "BroadcastChannel" in window ? new BroadcastChannel("mosuke_overlay") : null;

let lastStateT = 0;

function saveState(S) {
  S.t = Math.max(Date.now(), lastStateT + 1); // 連打で同じミリ秒になっても取りこぼさない
  lastStateT = S.t;
  try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch (e) {}
  if (chan) chan.postMessage(S);
  fbWrite("state", S);
}

// 新しいものだけ受け取る（同じ更新が BroadcastChannel と Firebase の両方から届くため）
function onState(cb) {
  const take = (s) => {
    if (!s || !(s.t > lastStateT)) return;
    lastStateT = s.t;
    s = normalizeState(s);
    try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch (e) {}
    cb(s);
  };
  if (chan) chan.onmessage = (e) => take(e.data);
  window.addEventListener("storage", (e) => {
    if (e.key === STORE_KEY && e.newValue) take(JSON.parse(e.newValue));
  });
  fbListen("state", take);
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
