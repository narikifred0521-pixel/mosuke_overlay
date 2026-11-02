// 川西モルック検定RTA … kentei.html（オーバーレイ）と kentei_control.html（操作）で共有する部分
// 状態の同期は MöSUKE と同じ（BroadcastChannel + localStorage + ルーム名があれば Firebase）。
// Firebase は mosuke_overlay/<room>/kentei に書く（DBのルールは mosuke_overlay 配下で許可済み）。

// ── 検定の中身（出典：川西モルックの会「川西モルック検定」） ──────────
const GRADES = [
  { g: 12, name: "4m 通常",   cond: "4mに並んだスキットルを1本だけ倒す" },
  { g: 11, name: "4m 後ろ",   cond: "前後に並んだ2本の後ろだけ倒す" },
  { g: 10, name: "4m 真ん中", cond: "横に並んだ3本の真ん中だけ倒す" },
  { g: 9,  name: "4m 飛ばし", cond: "4mのスキットルを8mより遠くへ飛ばす" },
  { g: 8,  name: "4m 手前",   cond: "前後に並んだ2本の前だけ倒す" },
  { g: 7,  name: "6m 後ろ",   cond: "前後に並んだ2本の後ろだけ倒す" },
  { g: 6,  name: "6m 真ん中", cond: "横に並んだ3本の真ん中だけ倒す" },
  { g: 5,  name: "8m 遠投",   cond: "8mのスキットルを1本だけ倒す" },
  { g: 4,  name: "6m 飛ばし", cond: "6mのスキットルを10mより遠くへ飛ばす" },
  { g: 3,  name: "6m 手前",   cond: "前後に並んだ2本の前だけ倒す" },
  { g: 2,  name: "10m 遠投",  cond: "10mのスキットルを1本だけ倒す" },
  { g: 1,  name: "12m 遠投",  cond: "12mのスキットルを1本だけ倒す" },
];
const THROWS = 12;          // 1回の受検で投げる数
const NEED = 7;             // 合格に必要な成功数
const MAX_MISS = THROWS - NEED; // これを超えたら不合格（6本目のミスで決まる）

const gradeInfo = (g) => GRADES.find((x) => x.g === g);

// ── 状態 ─────────────────────────────────────────
// start/stop … タイマー（ms）。stop が入ったらゴール
// grade … 今の級。log … 今の挑戦の記録 ["c","m",...]。tries[g] … その級の何回目か
// done[g] … 合格したときの経過ms。hist … 終わった挑戦の記録
// fx … 演出 { type, text, sub, t }
const K_STORE = "kentei_rta_state_v1";
const K_ROOM = "kentei_rta_room";

function blankState() {
  return { start: 0, stop: 0, grade: 12, log: [], tries: { 12: 1 }, done: {}, hist: [],
    show: { timer: true, hud: true, progress: true }, sfx: { control: true, overlay: true, vol: 0.8 }, fx: null, t: Date.now() };
}

// Firebase は空の配列・オブジェクトを消し、数字キーを配列にするので形を整える
function normalize(s) {
  const b = blankState();
  s = Object.assign(b, s || {});
  s.show = Object.assign(blankState().show, s.show);
  s.sfx = Object.assign(blankState().sfx, s.sfx);
  const toObj = (x) => {
    if (!x) return {};
    if (Array.isArray(x)) { const o = {}; x.forEach((v, i) => { if (v != null) o[i] = v; }); return o; }
    return Object.assign({}, x);
  };
  s.tries = toObj(s.tries); s.done = toObj(s.done);
  s.log = Array.isArray(s.log) ? s.log.filter(Boolean) : Object.values(s.log || {});
  s.hist = (Array.isArray(s.hist) ? s.hist : Object.values(s.hist || {})).filter(Boolean)
    .map((h) => Object.assign({}, h, { log: Array.isArray(h.log) ? h.log : Object.values(h.log || {}) }));
  if (!s.tries[s.grade]) s.tries[s.grade] = 1;
  return s;
}

// 今の挑戦の集計
function tally(log) {
  const c = log.filter((x) => x === "c").length, m = log.filter((x) => x === "m").length;
  const st = c >= NEED ? "pass" : m > MAX_MISS ? "fail" : "play";
  return { c, m, n: log.length, st, left: NEED - c };
}

function elapsed(S, now = Date.now()) {
  if (!S.start) return 0;
  return (S.stop || now) - S.start;
}

function fmtTime(ms, withSec = true) {
  const t = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const p = (x) => String(x).padStart(2, "0");
  return withSec ? `${h}:${p(m)}:${p(s)}` : `${h}:${p(m)}`;
}

// ── 同期 ─────────────────────────────────────────
const FB_URL = "https://morumasa-score-4818b-default-rtdb.asia-southeast1.firebasedatabase.app";
const ROOM = (new URLSearchParams(location.search).get("room") || (() => { try { return localStorage.getItem(K_ROOM); } catch (e) { return ""; } })() || "")
  .replace(/[^\w-]/g, "");
let fbDb = null, fbStatus = ROOM ? "接続中…" : "オフ";
const fbStatusCbs = [];
function setFbStatus(t) { fbStatus = t; fbStatusCbs.forEach((f) => f(t)); }

if (ROOM && window.firebase) {
  try {
    firebase.initializeApp({ databaseURL: FB_URL });
    fbDb = firebase.database();
    fbDb.ref(".info/connected").on("value", (s) => setFbStatus(s.val() ? "接続OK" : "接続中…"));
  } catch (e) { setFbStatus("エラー"); }
}
const fbRef = () => fbDb.ref(`mosuke_overlay/${ROOM}/kentei`);

let lastT = 0;
const chan = "BroadcastChannel" in window ? new BroadcastChannel("kentei_rta") : null;

function loadState() {
  try {
    const s = JSON.parse(localStorage.getItem(K_STORE));
    if (s) { lastT = s.t || 0; return normalize(s); }
  } catch (e) {}
  return blankState();
}

function saveState(S) {
  S.t = Math.max(Date.now(), lastT + 1);
  lastT = S.t;
  try { localStorage.setItem(K_STORE, JSON.stringify(S)); } catch (e) {}
  if (chan) chan.postMessage(S);
  if (fbDb) fbRef().set(JSON.parse(JSON.stringify(S))).catch(() => setFbStatus("書き込み不可"));
}

// 新しいものだけ受け取る（同じ更新が複数の経路から届くため）
function onState(cb) {
  const take = (s) => {
    if (!s || !(s.t > lastT)) return;
    lastT = s.t;
    s = normalize(s);
    try { localStorage.setItem(K_STORE, JSON.stringify(s)); } catch (e) {}
    cb(s);
  };
  if (chan) chan.onmessage = (e) => take(e.data);
  addEventListener("storage", (e) => { if (e.key === K_STORE && e.newValue) take(JSON.parse(e.newValue)); });
  if (fbDb) fbRef().on("value", (snap) => take(snap.val()), () => setFbStatus("読み込み不可"));
}

// ── 効果音（MöSUKEと同じ sfx/ を使う） ──────────────
function makeSounds(names) {
  const o = {};
  for (const n of names) {
    const a = new Audio(`sfx/${n}.mp3`);
    a.preload = "auto";
    a.addEventListener("error", () => { if (!a.dataset.fallback) { a.dataset.fallback = "1"; a.src = `sfx/${n}.wav`; } });
    o[n] = a;
  }
  return o;
}
