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

// 目安ペース：スタートから各級に合格するまでの累計分（12級→1級の順）。操作画面の「目安」で変えられる
// 初期値は 5:00スタート → 12級5:30・11級6:15・10級7:05・9級7:50・8級8:40・7級9:40・6級10:50・5級11:50
//          → 4級12:50・3級14:00・2級15:20・1級17:00 ゴール（18:00締切まで1時間の余裕。2026-11-02 古田さん「10:40は絶対無理」で見直し）
const DEFAULT_PACE = [30, 75, 125, 170, 220, 280, 350, 410, 470, 540, 620, 720];
const paceMs = (S, g) => (S.pace || DEFAULT_PACE)[12 - g] * 60000;
// その級の目安との差（ms）。合格済みなら合格時点、挑戦中なら今の時点。＋は遅れ
function paceDiff(S, g, now = Date.now()) {
  const t = S.done[g] != null ? S.done[g] : elapsed(S, now);
  return t - paceMs(S, g);
}
function fmtDiff(ms) {
  const t = Math.round(Math.abs(ms) / 1000), h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), x = t % 60;
  const p = (v) => String(v).padStart(2, "0");
  return (ms > 0 ? "+" : "−") + (h ? `${h}:${p(m)}:${p(x)}` : `${m}:${p(x)}`);
}

const gradeInfo = (g) => GRADES.find((x) => x.g === g);

// ── 状態 ─────────────────────────────────────────
// start/stop … タイマー（ms）。stop が入ったらゴール
// grade … 今の級。log … 今の挑戦の記録 ["c","m",...]。tries[g] … その級の何回目か
// done[g] … 合格したときの経過ms。hist … 終わった挑戦の記録
// fx … 演出 { type, text, sub, t }
const K_STORE = "kentei_rta_state_v1";
const K_ROOM = "kentei_rta_room";

function blankState() {
  return { start: 0, stop: 0, limit: "18:00:00", pace: DEFAULT_PACE.slice(), grade: 12, log: [], tries: { 12: 1 }, done: {}, hist: [],
    show: { timer: true, hud: true, progress: true }, size: 0.75, fx: null, t: Date.now() };
}

// Firebase は空の配列・オブジェクトを消し、数字キーを配列にするので形を整える
function normalize(s) {
  const b = blankState();
  s = Object.assign(b, s || {});
  s.show = Object.assign(blankState().show, s.show);
  delete s.sfx; delete s.sfxOff; // 音は使わない（2026-11-02 古田さん「音はなし」）
  // 表示の大きさ（1 = 作ったときの大きさ）。操作画面の「表示の大きさ」で変える
  s.size = Math.min(1.2, Math.max(0.4, Number(s.size) || 0.75));
  s.pace = (Array.isArray(s.pace) ? s.pace : Object.values(s.pace || {})).map(Number);
  if (s.pace.length !== 12 || s.pace.some((x) => !(x > 0))) s.pace = DEFAULT_PACE.slice();
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

// 締切の時刻（ms）。スタートした日の limit（"HH:MM[:SS]"）。スタート前は今日の limit
function deadline(S) {
  const [h, m, sec] = String(S.limit || "18:00:00").split(":").map(Number);
  const d = new Date(S.start || Date.now());
  d.setHours(h, m, sec || 0, 999);
  if (S.start && d.getTime() <= S.start) d.setDate(d.getDate() + 1); // 締切がスタートより前なら翌日の同じ時刻
  return d.getTime();
}

// 締切までの残り（ゴールしたらゴール時点の残り）
function remaining(S, now = Date.now()) {
  return deadline(S) - (S.stop || now);
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

// ── 編集用ログ（裏で全部残す。取り消し・リセットしても消さない） ──────────
// 1行 = { at: 時刻ms, ev: start|throw|pass|fail|next|retry|undo|goal|fix, g, try, n, r, el: 経過ms }
// この端末の localStorage と Firebase（mosuke_overlay/<room>/kentei_log）の両方に追記する
const K_EVENTS = "kentei_rta_events";

function logEvent(e) {
  e = Object.assign({ at: Date.now() }, e);
  try {
    const a = JSON.parse(localStorage.getItem(K_EVENTS) || "[]");
    a.push(e);
    localStorage.setItem(K_EVENTS, JSON.stringify(a));
  } catch (x) {}
  if (fbDb) fbDb.ref(`mosuke_overlay/${ROOM}/kentei_log`).push(e).catch(() => {});
}

async function loadEvents() {
  let local = [];
  try { local = JSON.parse(localStorage.getItem(K_EVENTS) || "[]"); } catch (x) {}
  if (!fbDb) return local;
  try {
    const snap = await fbDb.ref(`mosuke_overlay/${ROOM}/kentei_log`).once("value");
    const remote = Object.values(snap.val() || {});
    const seen = new Set(remote.map((e) => `${e.at}|${e.ev}`));
    return remote.concat(local.filter((e) => !seen.has(`${e.at}|${e.ev}`))).sort((a, b) => a.at - b.at);
  } catch (x) { return local; }
}

function eventsCsv(evs) {
  const p = (x, n = 2) => String(x).padStart(n, "0");
  const clock = (ms) => { const d = new Date(ms); return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`; };
  const name = { start: "スタート", throw: "投擲", pass: "合格", fail: "不合格", next: "次の級へ", retry: "やり直し", undo: "取り消し", goal: "ゴール", fix: "修正", star: "★見せ場", rec: "録画スタート" };
  const rows = [["時刻", "経過", "種類", "級", "回目", "投目", "結果", "成功数"]];
  for (const e of evs) {
    rows.push([clock(e.at), e.el != null ? fmtTime(e.el) : "", name[e.ev] || e.ev, e.g || "", e.try || "", e.n || "",
      e.r === "c" ? "○" : e.r === "m" ? "✕" : "", e.c != null ? e.c : ""]);
  }
  return "﻿" + rows.map((r) => r.join(",")).join("\n");
}
