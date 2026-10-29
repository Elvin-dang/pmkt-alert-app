"use strict";
// PMKT Alert UI. All data comes from window.pywebview.api (Python Api class); nothing is hard-coded.
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v) => v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v));
const money = (v) => (num(v) ? "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "—");
const pct = (v, d = 0) => (num(v) ? (v * 100).toFixed(d) + "%" : "—");
const signed = (v) => (num(v) ? (v >= 0 ? "+" : "−") + Math.abs(v * 100).toFixed(0) + "%" : "—");
const ddmm = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "");
const short = (label) => String(label || "").split(" – ")[0];
const SEV = { HIGH: 0, MED: 1, LOW: 2, "": 3 };
const ROLE_NAME = { tracker: "Data (raw_sso_us, Product Info, KPI, ads_camp, Inventory AMZ…)", ads: "Ads by Campaign (ads_camp)", activity: "Activity Log", logic: "Logic", defind: "Defind" };

let api = null;
const S = { paths: [], roles: null, run: null, ai: null, runId: null, pic: null, open: new Set(), update: null, fb: null, origSlack: "" };

// ------------------------------------------------------------------ helpers
function bad(r) {
  if (r && r.error) { toast(r.error, true); return true; }
  return false;
}
function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.setAttribute("role", err ? "alert" : "status");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 8000 : 4000);
}
const raw = (v) => `<span data-no-i18n>${esc(v)}</span>`;  // Claude / user text: never run through the UI translation
function sev(s) { return s ? `<span class="sev ${esc(s)}">${esc(s)}</span>` : ""; }
function fbBtn(unit, label, done) {
  return `<button class="fb${done ? " done" : ""}" data-unit="${esc(unit)}" data-label="${esc(label)}"><svg class="i" aria-hidden="true"><use href="#flag"/></svg>${done ? "Đã góp ý" : "Chưa hợp lý"}</button>`;
}
function copyText(text) {
  const fallback = () => {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  };
  try { navigator.clipboard.writeText(text).catch(fallback); } catch { fallback(); }
}
function store(key, value) {
  try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { return null; }
}
function md(text) {
  const inline = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  let out = "", inList = false;
  for (const line of String(text || "").split(/\r?\n/)) {
    const li = line.match(/^\s*[-*]\s+(.*)/);
    if (li) { if (!inList) { out += "<ul>"; inList = true; } out += `<li>${inline(li[1])}</li>`; continue; }
    if (inList) { out += "</ul>"; inList = false; }
    const h = line.match(/^#{1,6}\s+(.*)/);
    if (h) out += `<h3>${inline(h[1])}</h3>`;
    else if (line.trim()) out += `<p>${inline(line)}</p>`;
  }
  return out + (inList ? "</ul>" : "");
}

// ------------------------------------------------------------------ navigation & theme
function go(id) {
  $$("main section").forEach((s) => s.classList.toggle("on", s.id === id));
  $$("nav button").forEach((b) => (b.dataset.go === id ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
  if (id === "review") loadReview();
  if (id === "dashboard") loadDashboard();
  if (id === "perf") loadPerf();
  if (id === "lessons") loadLessons();
  if (id === "settings") loadSettings();
}
function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; }
function applyLang(l) {
  I18N.set(l);
  $("#lang").textContent = I18N.lang === "en" ? "VI" : "EN";
  $("#lang").title = I18N.lang === "en" ? "Chuyển sang tiếng Việt" : "Switch to English";
  $("#su-lang").textContent = I18N.lang === "en" ? "Tiếng Việt" : "English";
}

// ------------------------------------------------------------------ Claude status
async function checkClaude() {
  setPill("warn", "Đang kiểm tra…", "");
  const s = await api.claude_status();
  if (bad(s)) return;
  const text = s.level === "ok" ? "Sẵn sàng" : !s.installed ? "Chưa cài" : !s.logged_in ? "Chưa đăng nhập" : "Chậm/không ổn định";
  setPill(s.level, text + (!s.installed ? " – bấm để cài" : !s.logged_in ? " – bấm để đăng nhập" : ""), [s.version, s.latency_s != null ? `phản hồi ${s.latency_s}s` : "", s.detail].filter(Boolean).join(" · "));
  $("#cc-checks").innerHTML = [
    [s.installed, "Đã cài đặt", s.version ? `<code class="muted">${esc(s.version)}</code>` : "Bấm “Cài Claude Code” bên dưới"],
    [s.logged_in, "Đã đăng nhập", s.logged_in ? "" : "Bấm “Đăng nhập Claude Code” bên dưới"],
    [s.responds, "Phản hồi thử", s.latency_s != null ? `<span class="muted num">${s.latency_s}s</span>` : esc(s.detail || "")],
  ].map(([ok, label, extra]) => `<div class="check"><span class="sev ${ok ? "OK" : "HIGH"}">${ok ? "OK" : "LỖI"}</span>${label} ${extra}</div>`).join("");
  $("#cc-install").classList.toggle("hidden", s.installed);
  $("#cc-login").classList.toggle("hidden", !s.installed || s.logged_in);
  const hint = !s.installed ? "Cài bản chính thức của Anthropic (không cần quyền admin), sau đó đăng nhập bằng tài khoản Claude của bạn."
    : !s.logged_in ? "Bấm Đăng nhập → cửa sổ Terminal mở ra, làm theo hướng dẫn trên trình duyệt, xong quay lại bấm Kiểm tra lại." : "";
  $("#cc-hint").textContent = hint;
  $("#cc-hint").classList.toggle("hidden", !hint);
  S.claudeLevel = s.level;
}
async function installClaude() {
  const cmd = navigator.userAgent.includes("Windows") ? "irm https://claude.ai/install.ps1 | iex" : "curl -fsSL https://claude.ai/install.sh | bash";
  if (!confirm(I18N.t(`Cài Claude Code bằng trình cài đặt chính thức của Anthropic?\n\n${cmd}\n\nCần kết nối Internet, mất khoảng 1–2 phút.`))) return;
  const b = $("#cc-install");
  b.disabled = true;
  b.innerHTML = '<span class="spin"></span> Đang cài…';
  setPill("warn", "Đang cài…", "");
  const r = await api.install_claude();
  b.disabled = false;
  b.innerHTML = '<svg class="i" aria-hidden="true"><use href="#download"/></svg>Cài Claude Code';
  if (bad(r)) return;
  if (!r.ok) { toast("Cài chưa thành công: " + (r.output || "").slice(-300), true); await checkClaude(); return; }
  toast("Đã cài Claude Code. Bước tiếp: đăng nhập.");
  await checkClaude();
}
async function loginClaude() {
  if (!bad(await api.open_claude_login())) toast("Đã mở Terminal – đăng nhập xong thì bấm Kiểm tra lại.");
}
function setPill(level, text, title) {
  const p = $("#cc-pill");
  p.className = "pill " + level;
  p.title = title || "";
  $("#cc-text").textContent = "Claude Code: " + text;
  $("#cc-foot").textContent = "Claude Code ● " + text.toLowerCase();
}

// ------------------------------------------------------------------ run screen
const DAILY = new Set(["tracker", "ads", "activity"]);
function ago(iso) {
  const t = new Date(iso), now = new Date();
  const days = Math.round((new Date(now.toDateString()) - new Date(t.toDateString())) / 864e5);
  const hm = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  return { days, text: days === 0 ? `hôm nay ${hm}` : days === 1 ? `hôm qua ${hm}` : `${ddmm(iso)}/${iso.slice(0, 4)} ${hm} · ${days} ngày trước` };
}
function slot(role) {
  let r = S.roles && S.roles[role];
  const noAds = role === "tracker" && r && !S.roles.ads;  // Data file without ads_camp
  const m = r && r.modified ? ago(r.modified) : null;
  const stale = m && DAILY.has(role) && m.days >= 2;
  return `<div class="slot ${r ? "clickable" : ""}" ${r ? `role="button" tabindex="0" data-slot="${role}" aria-label="Xem chi tiết ${esc(r.name)}"` : ""}>
    <svg class="i" aria-hidden="true"><use href="#file"/></svg><div style="min-width:0"><div class="name">${esc(r ? r.name : ROLE_NAME[role])}</div>
    <div class="meta">${r ? `${esc(ROLE_NAME[role])} · ${r.size_mb ? r.size_mb : "<0.1"} MB` : "Chưa có file"}</div>
    ${m ? `<div class="meta" style="${stale ? "color:var(--med);font-weight:600" : ""}" title="Lần lưu gần nhất (Last modified)">Sửa lần cuối: ${m.text}${stale ? " – data có thể đã cũ" : ""}</div>` : ""}</div>
    ${noAds ? '<div class="meta" style="color:var(--high);font-weight:600">Thiếu sheet ads_camp trong file Data</div>' : ""}
    <span class="badges">${r && r.new ? '<span class="sev INFO" title="File đã thay đổi kể từ lần chạy trước">MỚI</span>' : ""}<span class="st sev ${r && !noAds ? "OK" : "MED"}">${r && !noAds ? "HỢP LỆ" : "THIẾU"}</span></span></div>`;
}
async function openFileDetail(role) {
  const r = S.roles[role];
  $("#fd-title").textContent = r.name;
  $("#fd-body").innerHTML = '<div class="muted"><span class="spin"></span> Đang đọc file…</div>';
  $("#fd").classList.add("on");
  const d = await api.file_detail(r.paths || [r.path]);
  if (d.error) { $("#fd-body").innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
  $("#fd-body").innerHTML = d.files.map((f) => {
    const m = ago(f.modified);
    return `<div class="card" style="margin-bottom:10px">
      <h3 style="margin:0 0 8px;font-size:14px" data-no-i18n>${esc(f.name)}</h3>
      <dl class="kv"><dt>Vai trò</dt><dd>${esc(ROLE_NAME[f.role] || f.role || "—")}</dd>
        <dt>Sửa lần cuối</dt><dd><b>${m.text}</b></dd><dt>Dung lượng</dt><dd>${(f.size / 1048576).toFixed(2)} MB</dd>
        <dt>Thư mục</dt><dd class="num" style="word-break:break-all" data-no-i18n>${esc(f.folder)}</dd></dl>
      ${f.sheets.map((sh) => `<details class="evsec" ${f.sheets.length === 1 ? "open" : ""}><summary><b data-no-i18n>${esc(sh.name)}</b> · <span class="num">${sh.rows.toLocaleString("en-US")}</span> dòng · ${sh.columns.length} cột${sh.dates.column ? ` · dữ liệu <span class="num">${ddmm(sh.dates.min)}/${sh.dates.min.slice(0, 4)} – ${ddmm(sh.dates.max)}/${sh.dates.max.slice(0, 4)}</span>` : ""}</summary>
        ${sh.dates.column ? `<p class="muted" style="font-size:12px;margin:6px 0">Khoảng ngày theo cột <code data-no-i18n>${esc(sh.dates.column)}</code></p>` : ""}
        ${sh.preview.rows.length ? `<div class="tbl" style="max-height:260px" data-no-i18n><table><thead><tr>${sh.preview.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
          <tbody>${sh.preview.rows.map((row) => `<tr>${row.map((v) => `<td class="${typeof v === "number" ? "n" : ""}">${v == null ? "" : esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
          <p class="muted" style="font-size:12px;margin:4px 0 0">${sh.preview.rows.length} dòng đầu${sh.columns.length > sh.preview.columns.length ? ` · ${sh.preview.columns.length}/${sh.columns.length} cột đầu` : ""}</p>` : '<div class="empty">Sheet trống</div>'}
      </details>`).join("")}</div>`;
  }).join("");
}
function renderSlots() {
  const ro = S.roles || {};
  $("#slots-data").innerHTML = ["tracker", "activity"].map(slot).join("");
  $("#slots-setting").innerHTML = slot("logic");
  $("#run-btn").disabled = !S.roles || ROLES.some((role) => !S.roles[role]);
}
const ROLES = ["tracker", "ads", "activity", "logic"];
async function useInputs(paths) {
  if (!paths || !paths.length) return;
  // New picks go first so they replace an earlier file of the same role.
  const r = await api.detect([...paths, ...S.paths]);
  if (bad(r)) return;
  S.roles = r.roles;
  S.paths = [...new Set(Object.values(r.roles).flatMap((x) => x.paths || [x.path]))];
  const msgs = [];
  if (r.missing.length) msgs.push("Còn thiếu: " + r.missing.filter((m) => !(m === "ads" && r.roles.tracker)).map((m) => ROLE_NAME[m]).join(", ")
    + (r.tracker_missing?.length ? ` (CSV còn thiếu: ${r.tracker_missing.join(", ")})` : ""));
  if (r.unknown.length) msgs.push("Không nhận ra: " + r.unknown.join(", "));
  $("#input-error").textContent = msgs.join(" · ");
  renderSlots();
}
window.onDropPaths = (paths) => { go("run"); useInputs(paths); };
const STEPS = { load: "Đọc & làm sạch data", logic: "Kiểm tra file logic", rules: "Tầng 0–4 – Data check · Pacing · Trend · Campaign · Action log", claude: "Claude – Insight · To-do · Tin nhắn", review: "Claude rà soát logic", logic_eval: "Claude đánh giá lỗi file logic" };
const STEP_STATE = {};
let RUN_T0 = 0, ETA = null, ETA_AT = 0, ETA_TIMER = null;
function fmtSecs(s) {
  s = Math.max(0, Math.round(s));
  const [sec, min] = I18N.lang === "en" ? ["s", "min"] : ["giây", "phút"];
  return s < 60 ? `${s} ${sec}` : `${Math.floor(s / 60)} ${min} ${String(s % 60).padStart(2, "0")} ${sec}`;
}
function renderEta() {
  const el = $("#eta");
  if (!el) return;
  const elapsed = (Date.now() - RUN_T0) / 1000;
  if (ETA == null) { el.textContent = `Đã chạy ${fmtSecs(elapsed)}`; return; }
  const left = Math.max(0, ETA - (Date.now() - ETA_AT) / 1000);
  const share = elapsed + left > 0 ? Math.min(99, (elapsed / (elapsed + left)) * 100) : 0;
  el.innerHTML = `Đã chạy ${fmtSecs(elapsed)} · <b>còn khoảng ${left < 1 ? "vài giây" : fmtSecs(left)}</b>`;
  $("#eta-bar").style.width = share + "%";
}
function stepLine(k, v, sub) {
  const badge = v.state === "running" ? '<span class="spin" aria-label="đang chạy"></span>' : `<span class="sev ${v.state === "done" ? "OK" : "MED"}">${v.state === "done" ? "XONG" : "CẢNH BÁO"}</span>`;
  const label = k.startsWith("pic:") ? k.slice(4) : STEPS[k] || k;
  return `<div class="check" ${sub ? 'style="padding-left:22px"' : ""}>${badge}${esc(label)} <span class="muted">${v.detail ? "— " + esc(v.detail) : ""}</span></div>`;
}
window.onProgress = (step, state, detail, extra) => {
  if (!RUN_T0) RUN_T0 = Date.now();
  STEP_STATE[step] = { state, detail };
  if (extra && extra.eta != null) { ETA = extra.eta; ETA_AT = Date.now(); }
  const subs = Object.keys(STEP_STATE).filter((k) => k.startsWith("pic:") || k === "review");
  const n = subs.length, fin = subs.filter((k) => STEP_STATE[k].state !== "running").length;
  $("#progress").innerHTML = `<div class="prog" aria-hidden="true"><span id="eta-bar"></span></div><p class="muted" id="eta" style="font-size:12px;margin:0 0 6px" role="status"></p>` +
    Object.entries(STEP_STATE).filter(([k]) => !subs.includes(k)).map(([k, v]) =>
      stepLine(k, k === "claude" && n ? { ...v, detail: `${fin}/${n} phần xong · ${v.detail}` } : v, false) +
      (k === "claude" ? subs.map((s) => stepLine(s, STEP_STATE[s], true)).join("") : "")).join("");
  renderEta();
};
function runningUi(on) {
  clearInterval(ETA_TIMER);
  if (on) { RUN_T0 = Date.now(); ETA = null; ETA_TIMER = setInterval(renderEta, 1000); }
  else if ($("#eta")) { $("#eta").textContent = `Xong sau ${fmtSecs((Date.now() - RUN_T0) / 1000)}`; $("#eta-bar").style.width = "100%"; }
  $("#run-btn").classList.toggle("hidden", on);
  $("#stop-btn").classList.toggle("hidden", !on);
  $("#stop-btn").disabled = false;
  $("#stop-btn").innerHTML = '<svg class="i" aria-hidden="true"><use href="#x"/></svg>Dừng';
}
async function stopRun() {
  $("#stop-btn").disabled = true;
  $("#stop-btn").innerHTML = '<span class="spin"></span> Đang dừng…';
  await api.cancel_run();
}
function runError(r) {
  // A failing step stops the run: drop the progress view, say what to fix and exactly where.
  clearInterval(ETA_TIMER);
  const loc = r.location || {};
  const where = loc.file ? `<div class="kv" style="margin-top:8px"><dt>File</dt><dd data-no-i18n>${esc(loc.file)}</dd>
      ${loc.sheet ? `<dt>Sheet</dt><dd data-no-i18n>${esc(loc.sheet)}</dd>` : ""}
      ${loc.columns ? `<dt>Cột cần có</dt><dd data-no-i18n><b>${loc.columns.map(esc).join(", ")}</b>${loc.row ? ` (dòng tiêu đề ${loc.row})` : ""}</dd>` : ""}
      ${loc.cell ? `<dt>Ô</dt><dd data-no-i18n><b>${esc(loc.cell)}</b></dd>` : ""}</div>` : "";
  $("#progress").innerHTML = `<div class="run-error" role="alert"><div style="display:flex;gap:8px;align-items:center"><span class="sev HIGH">LỖI</span>
      <b>Dừng ở bước: ${esc(STEPS[r.step] || r.step || "Đọc dữ liệu")}</b></div>
    <p style="margin:8px 0 0">${esc(r.error)}</p>${where}
    <p class="muted" style="font-size:12px;margin:8px 0 0">Sửa file theo chỉ dẫn trên, lưu lại, rồi bấm Chạy lần nữa.</p></div>`;
  $("#input-error").textContent = "";
}
async function doRun() {
  $("#run-btn").disabled = true;
  runningUi(true);
  Object.keys(STEP_STATE).forEach((k) => delete STEP_STATE[k]);
  window.onProgress("load", "running", "");
  if ($("#use-claude").checked) await checkClaude();
  const r = await api.run(S.paths, $("#as-of").value || null, $("#use-claude").checked);
  runningUi(false);
  $("#run-btn").disabled = false;
  if (r.error) { runError(r); return; }
  useInputs(S.paths);  // files are no longer "Mới" after a run
  if (r.cancelled) { toast("Đã dừng – chưa có kết quả mới."); return; }
  setRun(r);
  if (r.stopped) toast("Đã dừng – kết quả rule đầy đủ, phần Claude bị bỏ dở.");
  if (r.ai && !r.ai.claude_ok) setPill("warn", "Lỗi ở lần chạy này", r.ai.error || "");
  go("results");
}

// ------------------------------------------------------------------ results
function setRun(r) {
  S.run = r.result; S.ai = r.ai; S.runId = r.run_id; S.open.clear(); S.db = null;
  const digest = [...S.run.digest].sort((a, b) => (b.pl_high + b.camp_high) - (a.pl_high + a.camp_high));
  if (!digest.some((d) => d.pic === S.pic)) S.pic = digest.length ? digest[0].pic : null;
  $("#pic").innerHTML = digest.map((d) => `<option ${d.pic === S.pic ? "selected" : ""}>${esc(d.pic)}</option>`).join("");
  const asOf = S.run.as_of;
  const d = new Date(asOf + "T00:00:00");
  const shift = (n) => { const x = new Date(d); x.setDate(x.getDate() + n); return `${String(x.getDate()).padStart(2, "0")}/${String(x.getMonth() + 1).padStart(2, "0")}`; };
  const modelTxt = S.run.model === "score_v3" ? " · mô hình chấm điểm" : "";
  $("#run-meta").innerHTML = `Data đến <span class="num">${ddmm(asOf)}/${asOf.slice(0, 4)}</span> · L7D ${shift(-6)}–${shift(0)} vs P7D ${shift(-13)}–${shift(-7)} · Logic <code>Ver ${S.run.logic_version}</code>${modelTxt}`;
  $("#f-run").textContent = `Lần chạy: ${S.runId}`;
  $("#f-logic").innerHTML = `Logic: <code>Ver ${S.run.logic_version}</code>`;
  const high = S.run.digest.reduce((a, x) => a + x.pl_high + x.camp_high, 0);
  $("#nav-results").textContent = high; $("#nav-results").classList.toggle("hidden", !high);
  renderResults();
}
function aiFor(pic) { return ((S.ai || {}).per_pic || {})[pic] || null; }
const F_DEFAULT = { sev: "HM", action: "", trend: "", status: "", q: "", sort: "sev", dir: 1, todoSev: "", todoDue: "" };
S.f = { ...F_DEFAULT };
function renderResults() {
  const body = $("#results-body");
  if (!S.run || !S.pic) { body.innerHTML = '<div class="empty" style="margin-top:12px">Chưa có kết quả – vào “Chạy dữ liệu”.</div>'; return; }
  const d = S.run.digest.find((x) => x.pic === S.pic);
  const mine = aiFor(S.pic);
  const issues = S.run.issues || [];
  const tab = S.tab || "t-alerts";
  const todos = mine ? mine.todos : [];
  body.innerHTML = `
    ${S.run.unreliable ? '<div class="warnbar"><svg class="i" aria-hidden="true"><use href="#alert"/></svg><b>CẢNH BÁO DATA</b> – xem tab Data trước khi action.</div>' : ""}
    ${logicBanner()}
    ${scoreModelHtml(d)}
    <div class="grid g5" style="margin-top:12px">
      <div class="card kpi"><div class="lbl">PL HIGH (pacing)</div><div class="val high num">${d.pl_high}</div></div>
      <div class="card kpi"><div class="lbl">PL MED (pacing)</div><div class="val med num">${d.pl_med}</div></div>
      <div class="card kpi"><div class="lbl">PL trend cần review</div><div class="val num">${d.pl_trend_review}</div></div>
      <div class="card kpi"><div class="lbl">Camp HIGH / MED · follow-up</div><div class="val num"><span style="color:var(--high)">${d.camp_high}</span> / <span style="color:var(--med)">${d.camp_med}</span> · ${d.camp_followup}</div></div>
      <div class="card kpi"><div class="lbl">Excess spend cần action</div><div class="val num">${money(d.excess_new)}</div></div>
    </div>
    <div class="tabs" role="tablist">
      ${[["t-alerts", "Cảnh báo"], ["t-todos", `To-do (${todos.length})`], ["t-insights", "Insight"], ["t-data", `Data ⚠ (${issues.length})`]]
        .map(([id, label]) => `<button role="tab" aria-selected="${id === tab}" data-tab="${id}">${label}</button>`).join("")}
    </div>
    <div class="tabpanel ${tab === "t-alerts" ? "on" : ""}" id="t-alerts">${filterBar()}${alertsTable()}</div>
    <div class="tabpanel ${tab === "t-todos" ? "on" : ""}" id="t-todos">${todosHtml(mine)}</div>
    <div class="tabpanel ${tab === "t-insights" ? "on" : ""}" id="t-insights">${insightsHtml(mine)}</div>
    <div class="tabpanel ${tab === "t-data" ? "on" : ""}" id="t-data">${issues.length ? issues.map((i) => `<div class="todo"><span class="sev ${i.severity === "WARN" ? "MED" : "INFO"}">${i.severity === "WARN" ? "DATA" : "INFO"}</span><div><div class="t">${esc(i.title)}</div><div class="d">${esc(i.detail)}</div></div></div>`).join("") : '<div class="empty">Data ổn.</div>'}</div>`;
  S.origSlack = mine ? mine.slack : "";
}
function logicBanner() {
  const errs = (S.run.logic_issues || []).filter((i) => i.hint === "error");
  if (!errs.length) return "";
  const crit = ((S.ai || {}).logic_eval?.items || []).filter((x) => x.verdict === "critical").length;
  return `<div class="warnbar"><svg class="i" aria-hidden="true"><use href="#alert"/></svg><b>FILE LOGIC</b> – ${esc(S.run.logic_file || "")}: ${errs.length} lỗi, đang dùng giá trị dự phòng${crit ? ` · <b>${crit} nghiêm trọng</b>` : ""}.
    <span style="flex:1"></span><button class="btn sm" data-goto="review">Xem hướng dẫn sửa</button></div>`;
}
function claudeMissing(mine) {
  const err = !S.ai ? "Lần chạy này không dùng Claude" : (mine && mine.error) || S.ai.error;
  return `<div class="empty"><b>Claude không sẵn sàng</b><br>${esc(err || "")}<br>Kết quả rule vẫn đầy đủ ở tab Cảnh báo.</div>`;
}
function evBtn(units, label = "Bằng chứng") {
  const list = (Array.isArray(units) ? units : [units]).filter((u) => /^(pl|camp|pic):/.test(u || ""));
  if (!list.length) return "";
  return `<button class="fb evb" data-ev="${esc(list.join("|"))}" title="Xem dữ liệu gốc: file, sheet, cột, dòng"><svg class="i" aria-hidden="true"><use href="#file"/></svg>${label}</button>`;
}
function opts(list, cur, all) {
  return [`<option value="">${esc(all)}</option>`, ...list.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`)].join("");
}
// SCALE UP = grow → green; otherwise colour follows severity.
function actionColor(action, sevLevel) {
  if (String(action || "").startsWith("SCALE UP") || String(action || "").startsWith("MAINTAIN/PUSH")) return "var(--ok)";
  return sevLevel === "HIGH" ? "var(--high)" : sevLevel === "MED" ? "var(--med)" : "var(--fg)";
}
function scoreModelHtml(d) {
  if (S.run.model !== "score_v3" || !S.run.dept) return "";
  const dp = S.run.dept, pic = (S.run.pics || []).find((x) => x.pic === S.pic);
  const regimeCls = dp.regime === "VƯỢT" ? "HIGH" : dp.regime === "CÒN ROOM" ? "OK" : "INFO";
  return `<div class="card" style="margin-top:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:13px">
    <span><b>Department</b> · target TACoS <b class="num">${pct(dp.target_tacos, 1)}</b> · actual <b class="num">${pct(dp.actual_tacos, 1)}</b>
      · coverage <span class="num">${pct(dp.coverage)}</span> · <span class="sev ${regimeCls}">${esc(dp.regime)}</span>
      · ngưỡng SCALE DOWN <b class="num">${esc(dp.sd_threshold)}</b></span>
    ${pic ? `<span style="flex:1"></span><span><b>${esc(S.pic)}</b> · <span class="lab" style="color:${actionColor(pic.pacing_action, pic.pacing_sev)}">${esc(pic.pacing_action)}</span>
      ${pic.score != null ? `· điểm <b class="num">${Math.round(pic.score)}</b>` : ""} · Excess$ vs Dept <b class="num">${money(pic.excess_dept)}</b>
      ${evBtn("pic:" + S.pic)}</span>` : ""}
  </div>`;
}
function filterBar() {
  const mineCamps = S.run.camp.filter((r) => r.pic === S.pic);
  const minePls = S.run.pl.filter((r) => r.pic === S.pic);
  const actions = [...new Set([...minePls.map((p) => short(p.pacing_action)), ...mineCamps.map((c) => short(c.base_action))])].sort();
  const trends = [...new Set(minePls.map((p) => p.trend_label).filter(Boolean))].sort();
  return `<div class="filters">
    <input type="search" id="f-q" placeholder="Tìm PL / campaign…" value="${esc(S.f.q)}" aria-label="Tìm">
    <select id="f-sev" aria-label="Mức">${opts([["HM", "HIGH + MED"], ["HIGH", "Chỉ HIGH"], ["MED", "Chỉ MED"], ["LOW", "Chỉ LOW"]], S.f.sev, "Mọi mức")}</select>
    <select id="f-action" aria-label="Action">${opts(actions.map((a) => [a, a]), S.f.action, "Mọi action")}</select>
    <select id="f-trend" aria-label="Trend">${opts(trends.map((t) => [t, t]), S.f.trend, "Mọi trend")}</select>
    <select id="f-status" aria-label="Trạng thái">${opts([["CHƯA ACTION", "Chưa action"], ["ĐÃ ACTION", "Đã action (follow-up)"], ["ACTION CŨ", "Action cũ"]], S.f.status, "Mọi trạng thái")}</select>
    <button class="btn sm ghost" id="f-reset">Xoá lọc</button>
    <span style="flex:1"></span><button class="btn sm" id="cols-btn" aria-haspopup="true"><svg class="i" aria-hidden="true"><use href="#cols"/></svg>Cột</button>
  </div>`;
}
const SEV_OK = (s, f) => !f || (f === "HM" ? s === "HIGH" || s === "MED" : s === f);
const SORTS = {
  sev: [(r) => SEV[r.pacing_sev ?? r.sev] ?? 3, 1], name: [(r) => (r.pl || r.campaign || "").toLowerCase(), 1],
  gmv: [(r) => r.pct_gmv ?? -1, -1], spend: [(r) => r.pct_spend ?? -1, -1], tacos: [(r) => r.actual_tacos ?? -1, -1],
  dspend: [(r) => r.d_spend ?? -9, -1], excess: [(r) => r._excess ?? r.excess ?? 0, -1],
  dnmv: [(r) => dNmv(r) ?? -9, -1], lastaction: [(r) => String(r.last_action_date || (r.pl && !r.campaign ? lastActionOfPl(r.pl) : "") || ""), -1],
  score: [(r) => r.score ?? -999, -1],
};
function sortRows(rows) {
  const [key, natural] = SORTS[S.f.sort] || SORTS.sev;
  const dir = natural * S.f.dir;
  return rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * dir || (SEV[a.pacing_sev ?? a.sev] ?? 3) - (SEV[b.pacing_sev ?? b.sev] ?? 3); });
}
function th(c) {
  const on = c.sort && S.f.sort === c.sort;
  const info = `<button class="colinfo" data-col="${c.key}" aria-label="Định nghĩa ${esc(c.label)}" title="Định nghĩa"><svg class="i" aria-hidden="true"><use href="#info"/></svg></button>`;
  return `<th class="${c.cls || ""}${c.sort ? " sortable" : ""}" ${c.sort ? `data-sort="${c.sort}" aria-sort="${on ? (S.f.dir === 1 ? "ascending" : "descending") : "none"}"` : ""}><span class="thw">${c.label}${on ? (S.f.dir === 1 ? " ▾" : " ▴") : ""}${info}</span></th>`;
}
function colInfo(btn) {
  const c = COLS.find((x) => x.key === btn.dataset.col), d = c.def, pop = $("#colpop");
  pop.innerHTML = `<div style="display:flex;align-items:center;gap:8px"><b style="flex:1">${esc(c.label)}</b>
      ${c.fixed ? "" : `<button class="btn sm ghost" data-hidecol="${c.key}">Ẩn cột</button>`}<button class="btn sm ghost" data-closepop aria-label="Đóng">✕</button></div>
    <p style="margin:6px 0">${esc(d.what)}</p>
    ${d.formula ? `<div class="poplab">Công thức</div><div class="code-box" style="font-size:12px">${esc(d.formula)}</div>` : ""}
    <div class="poplab">Lấy từ</div><ul>${d.map.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>
    ${d.note ? `<p class="muted" style="font-size:12px;margin:4px 0 0">${esc(d.note)}</p>` : ""}`;
  const r = btn.getBoundingClientRect();
  pop.classList.remove("hidden");
  const w = pop.offsetWidth;
  pop.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
  pop.style.top = Math.min(r.bottom + 6, innerHeight - pop.offsetHeight - 8) + "px";
  pop.querySelector("[data-closepop]").focus();
}
function colChooser(btn) {
  const pop = $("#colpop"), hide = hiddenCols(), v3 = S.run.model === "score_v3";
  pop.innerHTML = `<div style="display:flex;align-items:center"><b style="flex:1">Hiện / ẩn cột</b><button class="btn sm ghost" data-closepop aria-label="Đóng">✕</button></div>
    ${COLS.filter((c) => !c.v3 || v3).map((c) => `<label class="colchk"><input type="checkbox" data-togglecol="${c.key}" ${hide.has(c.key) && !c.fixed ? "" : "checked"} ${c.fixed ? "disabled" : ""}> ${esc(c.label)}</label>`).join("")}
    <button class="btn sm ghost" data-showall style="margin-top:6px">Hiện tất cả</button>`;
  const r = btn.getBoundingClientRect();
  pop.classList.remove("hidden");
  pop.style.left = Math.max(8, Math.min(r.right - pop.offsetWidth, innerWidth - pop.offsetWidth - 8)) + "px";
  pop.style.top = r.bottom + 6 + "px";
}
function setHidden(set) { store("hiddenCols2", JSON.stringify([...set])); renderResults(); }
// Result columns: header, cells (PL row / campaign row), sort key and the definition shown by the ⓘ button.
// Definitions follow the code (aggregate.py, rules/, evidence.py) – keep them in sync when a formula changes.
const COLS = [
  { key: "name", label: "Product Line / Campaign", sort: "name", fixed: true,
    def: { what: "PL là Product Line; bấm dòng PL để xem các campaign của PL đó.",
      map: ["PL: Product Info › product_line_old, nối ASIN → SKU → PL", "PIC: Product Info › cột PIC của tháng (v3: PMKT PIC_Final)", "Campaign: ads_camp › campaign_name, gán vào PL theo ASIN quảng cáo"] },
    pl: (p, kids, open) => `<td><b>${esc(p.pl)}</b>${kids.length ? ` <span class="muted">(${kids.length})</span>` : ""}</td>`,
    camp: (c) => `<td class="muted" title="${esc(c.campaign)}">${esc(c.campaign)}</td>` },
  { key: "sev", label: "Alert Level", sort: "sev",
    def: { what: "Mức độ ưu tiên của cảnh báo: HIGH (xử lý ngay), MED (trong tuần), LOW (theo dõi).",
      formula: "PL: theo rule pacing đầu tiên khớp · Campaign: theo ACoS camp ÷ ACoS PL, số click và excess spend",
      map: ["Ngưỡng: Alert_Logic › Config (vd. “Excess spend để lên HIGH”)"] },
    pl: (p) => `<td>${sev(p.pacing_sev)}</td>`, camp: (c) => `<td>${sev(c.sev)}</td>` },
  { key: "placode", label: "PL action code",
    def: { what: "Hướng ngân sách của Product Line (chỉ ở dòng PL).",
      formula: "Mô hình chấm điểm: điểm ≥ 50 → SCALE DOWN, ≥ 25 → OPTIMIZE, ≤ −25 → SCALE UP, còn lại MAINTAIN; luật cứng NO DATA / NO PLAN / KHÔNG CHẠY / CHƯA ĐỦ DATA / BUDGET CAP; chốt chặn tồn kho đổi SCALE UP → CHỜ HÀNG",
      map: ["Ngưỡng: Logic › Config (D, E, K)"] },
    pl: (p) => `<td class="lab" style="color:${actionColor(p.pacing_action, p.pacing_sev)}">${esc(short(p.pacing_action))}</td>`, camp: () => "<td></td>" },
  { key: "dspend2", label: "Change in spend", sort: "dspend", cls: "n",
    def: { what: "Thay đổi chi tiêu 7 ngày gần nhất so với 7 ngày trước đó.", formula: "Spend L7D ÷ Spend P7D − 1",
      map: ["PL: raw_sso_us › sp_spend + sb_spend + sd_spend", "Campaign: ads_camp › spend_usd"] },
    pl: (p) => `<td class="n">${signed(p.d_spend)}</td>`, camp: (c) => `<td class="n">${signed(c.d_spend)}</td>` },
  { key: "dnmv", label: "Change in NMV", sort: "dnmv", cls: "n",
    def: { what: "Thay đổi doanh thu 7 ngày gần nhất so với 7 ngày trước đó.", formula: "PL: GMV L7D ÷ GMV P7D − 1 · Campaign: sales L7D ÷ sales P7D − 1",
      map: ["PL: raw_sso_us › ordered_gmv_usd", "Campaign: ads_camp › sales_14d"] },
    pl: (p) => `<td class="n">${signed(dNmv(p))}</td>`, camp: (c) => `<td class="n">${signed(dNmv(c))}</td>` },
  { key: "lastaction", label: "Last action", sort: "lastaction",
    def: { what: "Hành động gần nhất của PIC trên campaign (PL: hành động mới nhất trong các campaign của PL).",
      formula: "Khớp Activity Log theo tên campaign; trong 3 ngày gần nhất = ĐÃ ACTION, cũ hơn mà vẫn còn cảnh báo = ACTION CŨ",
      map: ["Activity Log › Level (Campaign: …), Type, thời gian"] },
    pl: (p) => { const d = lastActionOfPl(p.pl); return `<td class="muted" style="white-space:nowrap">${d ? ddmm(d) : "—"}</td>`; },
    camp: (c) => `<td style="white-space:nowrap">${c.last_action_date ? `${ddmm(String(c.last_action_date))} <span class="muted">${esc(c.last_action_type || "")}</span>` : '<span class="muted">—</span>'}${c.status && c.sev ? ` <span class="chip">${esc(c.status)}</span>` : ""}</td>` },
  { key: "campcode", label: "Campaign action code",
    def: { what: "Việc nên làm với campaign (chỉ ở dòng campaign).",
      formula: "Chưa đủ click → WAIT; đủ click 0 order → PAUSE/NEGATE; còn lại so ACoS camp ÷ ACoS PL theo action của PL; ≥50% spend trên ASIN hết hàng → PAUSE – HẾT HÀNG, sắp hết → GIỮ – SẮP HẾT",
      map: ["ads_camp (L7D, P7D) · Logic › Config G, K"] },
    pl: () => "<td></td>",
    camp: (c) => `<td class="lab" style="color:${actionColor(c.base_action, "")}">${esc(c.final_label || short(c.base_action))}</td>` },
  { key: "reason", label: "Reason",
    def: { what: "Vì sao có cảnh báo / khuyến nghị.", formula: "PL: TACoS, target riêng & Dept, Excess$ vs Dept, GMV/Spend pace, điểm, tồn kho · Campaign: ACoS so với PL, click, excess, xu hướng, tồn kho",
      map: ["Tổng hợp từ các cột trên + Evidence"] },
    pl: (p) => `<td class="reason"><div title="${esc(p.pacing_reason || "")}">${esc(p.pacing_reason || "—")}</div></td>`,
    camp: (c) => { const t = campReason(c); return `<td class="reason"><div title="${esc(t)}">${esc(t || "—")}</div></td>`; } },
  { key: "action", label: "Pacing / Action", optional: true,
    def: { what: "Việc nên làm với PL / campaign.",
      formula: "PL (Ver 1): rule đầu tiên khớp theo thứ tự NO PLAN → KHÔNG CHẠY → SCALE DOWN → OPTIMIZE → SCALE UP → BUDGET CAP → CHECK → MAINTAIN, dựa trên GMV pace, Spend pace và TACoS ÷ target. PL (v3): theo Điểm và khung Department. Campaign: theo action của PL + ACoS camp ÷ ACoS PL; trạng thái (đã / chưa action) lấy từ Activity Log.",
      map: ["Ngưỡng: Alert_Logic › Config", "Trạng thái campaign: Activity Log › campaign + ngày action"] },
    pl: (p) => `<td class="lab" style="color:${actionColor(p.pacing_action, p.pacing_sev)}">${esc(short(p.pacing_action))}</td>`,
    camp: (c) => `<td class="lab" style="color:${actionColor(c.base_action, "")}">${esc(c.final_label || short(c.base_action))}</td>` },
  { key: "trend", label: "Trend L7D", optional: true,
    def: { what: "Xu hướng 7 ngày gần nhất (L7D) so với 7 ngày trước đó (P7D).",
      formula: "PL: Δ Spend, Δ ACoS, Δ TACoS so với ngưỡng → tạo key, tra bảng Matrix_PL ra nhãn · Campaign: Δ ACoS và Δ Spend của campaign",
      map: ["PL: raw_sso_us (spend, ppc_ordered_gmv_usd, ordered_gmv_usd)", "Campaign: ads_camp (spend_usd, sales_14d)", "Ngưỡng: Alert_Logic › Config (Spend / ACoS / TACoS) + sheet Matrix_PL"] },
    pl: (p) => `<td class="lab">${esc(p.trend_label || "—")}</td>`,
    camp: (c) => `<td class="muted">${esc(c.camp_trend ? c.camp_trend.replace("7D: ", "") : "")}</td>` },
  { key: "gmv", label: "GMV %", sort: "gmv", cls: "n", optional: true,
    def: { what: "Tiến độ GMV tháng so với target.", formula: "GMV MTD ÷ target GMV tháng",
      map: ["GMV MTD: raw_sso_us › ordered_gmv_usd, từ ngày 1 tới ngày data", "Target: KPI › GMV của tháng, cộng các ASIN của PL"],
      note: "So với time gone: GMV % ÷ time gone = GMV pace (1× là đúng tiến độ)." },
    pl: (p) => `<td class="n">${pct(p.pct_gmv)}</td>`, camp: () => "<td></td>" },
  { key: "spend", label: "Spend %", sort: "spend", cls: "n", optional: true,
    def: { what: "Tiến độ chi tiêu ads tháng so với target.", formula: "Spend MTD ÷ target spend tháng",
      map: ["Spend MTD: raw_sso_us › sp_spend + sb_spend + sd_spend", "Target: KPI › Spend_final của tháng"],
      note: "Spend % ÷ time gone = Spend pace." },
    pl: (p) => `<td class="n">${pct(p.pct_spend)}</td>`, camp: () => "<td></td>" },
  { key: "tacos", label: "TACoS", sort: "tacos", cls: "n", optional: true,
    def: { what: "PL: TACoS tháng / target TACoS. Campaign: ACoS của campaign so với ACoS chung của PL.",
      formula: "TACoS = Spend MTD ÷ GMV MTD · Target TACoS = target spend ÷ target GMV · Campaign: (spend L7D ÷ sales L7D của camp) ÷ (spend L7D ÷ sales L7D của mọi camp trong PL)",
      map: ["raw_sso_us (spend, ordered_gmv_usd) · KPI (GMV, Spend_final)", "Campaign: ads_camp › spend_usd, sales_14d"] },
    pl: (p) => `<td class="n">${pct(p.actual_tacos, 1)} <span class="muted">/${pct(p.target_tacos, 1)}</span></td>`,
    camp: (c) => `<td class="n">ACoS ${num(c.acos_ratio) ? Number(c.acos_ratio).toFixed(2) + "×" : "—"}</td>` },
  { key: "dspend", label: "Δ Spend", sort: "dspend", cls: "n", optional: true,
    def: { what: "Thay đổi chi tiêu 7 ngày gần nhất so với 7 ngày trước đó.", formula: "Spend L7D ÷ Spend P7D − 1",
      map: ["PL: raw_sso_us › sp_spend + sb_spend + sd_spend", "Campaign: ads_camp › spend_usd"] },
    pl: (p) => `<td class="n">${signed(p.d_spend)}</td>`, camp: (c) => `<td class="n">${signed(c.d_spend)}</td>` },
  { key: "score", label: "Điểm", sort: "score", cls: "n", v3: true, optional: true,
    def: { what: "Điểm tổng hợp của PL (chỉ với file logic mô hình chấm điểm v3). Âm = nên giảm, dương = có thể tăng.",
      formula: "Σ(w × s) ÷ Σw, với s1…s6 = (TACoS ÷ target − 1), (TACoS ÷ target Dept − 1), −(Ads dependency ÷ benchmark − 1), Δ TACoS, GMV pace − 1, Spend pace − 1; mỗi s chia độ nhạy × 100, giới hạn ±100",
      map: ["Trọng số w1–w6 và độ nhạy: Alert_Logic › Config"] },
    pl: (p) => `<td class="n">${p.score != null ? Math.round(p.score) : "—"}</td>`, camp: () => "<td></td>" },
  { key: "excess", label: "Excess $", sort: "excess", cls: "n", optional: true,
    def: { what: "Chi tiêu L7D vượt mức hợp lý – số tiền có thể cắt.", formula: "Campaign: MAX(0, spend L7D − sales L7D × ACoS L7D của PL) · PL: cộng excess của các campaign",
      map: ["ads_camp › spend_usd, sales_14d (7 ngày gần nhất)"] },
    pl: (p) => `<td class="n">${p._excess ? money(p._excess) : "—"}</td>`, camp: (c) => `<td class="n">${money(c.excess)}</td>` },
];
function hiddenCols() {
  // Default view = the Alert_brief "Update" columns; the older metrics stay available in "Cột".
  try { const saved = store("hiddenCols2"); if (saved) return new Set(JSON.parse(saved)); } catch { /* fall through */ }
  return new Set(COLS.filter((c) => c.optional).map((c) => c.key));
}
const dNmv = (r) => (r.p7d_gmv != null ? (r.p7d_gmv ? r.l7d_gmv / r.p7d_gmv - 1 : null) : r.p7d_sales ? r.l7d_sales / r.p7d_sales - 1 : null);
function lastActionOfPl(pl) {
  const ds = S.run.camp.filter((c) => c.pl === pl && c.pic === S.pic && c.last_action_date).map((c) => String(c.last_action_date));
  return ds.length ? ds.sort().at(-1) : null;
}
function campReason(c) {
  const parts = [];
  if (num(c.acos_ratio)) parts.push(`ACoS ${Number(c.acos_ratio).toFixed(2)}× PL`);
  if (num(c.l7d_clicks)) parts.push(`${Math.round(c.l7d_clicks)} click (cần ${c.min_clicks ?? "—"})`);
  if (c.excess > 0) parts.push(`excess ${money(c.excess)}`);
  if (c.camp_trend) parts.push(c.camp_trend);
  if (c.inv_note) parts.push(c.inv_note);
  if (c.followup_check) parts.push(c.followup_check);
  return parts.join(" · ");
}
function shownCols() {
  const hide = hiddenCols(), v3 = S.run.model === "score_v3";
  return COLS.filter((c) => (!c.v3 || v3) && (c.fixed || !hide.has(c.key)));
}
function alertsTable() {
  const f = S.f, q = f.q.trim().toLowerCase();
  const campOk = (c) => SEV_OK(c.sev, f.sev) && (!f.action || short(c.base_action) === f.action) && (!f.status || c.status === f.status)
    && (!q || c.campaign.toLowerCase().includes(q) || c.pl.toLowerCase().includes(q));
  const byPl = {};
  S.run.camp.filter((c) => c.pic === S.pic && campOk(c)).forEach((c) => (byPl[c.pl] = byPl[c.pl] || []).push(c));
  const plOk = (p) => !f.status && SEV_OK(p.pacing_sev, f.sev) && (!f.action || short(p.pacing_action) === f.action)
    && (!f.trend || p.trend_label === f.trend) && (!q || p.pl.toLowerCase().includes(q));
  const pls = S.run.pl.filter((p) => p.pic === S.pic && (plOk(p) || (byPl[p.pl] && (!f.trend || p.trend_label === f.trend))))
    .map((p) => ({ ...p, _excess: (byPl[p.pl] || []).reduce((a, c) => a + (c.excess || 0), 0) }));
  const visible = sortRows(pls);
  if (!visible.length) return '<div class="empty">Không có dòng nào khớp bộ lọc.</div>';
  const sent = new Set(S.feedbackUnits || []);
  const cols = shownCols();
  const rows = visible.map((p) => {
    const kids = sortRows(byPl[p.pl] || []);
    const open = S.open.has(p.pl) || (q && kids.length);
    const head = `<tr class="expandable" data-pl="${esc(p.pl)}" aria-expanded="${!!open}"><td>${kids.length ? `<svg class="i" aria-hidden="true" style="transform:rotate(${open ? 90 : 0}deg)"><use href="#chev"/></svg>` : ""}</td>
      ${cols.map((c) => c.pl(p, kids, open)).join("")}
      <td class="acts">${evBtn(p.unit_id)}${fbBtn(p.unit_id, `${p.pl} · ${short(p.pacing_action)}`, sent.has(p.unit_id))}</td></tr>`;
    const children = open ? kids.map((c) => `<tr class="child"><td></td>${cols.map((col) => col.camp(c)).join("")}
      <td class="acts">${evBtn(c.unit_id)}${fbBtn(c.unit_id, `${c.campaign} · ${short(c.final_label || c.base_action)}`, sent.has(c.unit_id))}</td></tr>`).join("") : "";
    return head + children;
  }).join("");
  const hiddenN = COLS.filter((c) => (!c.v3 || S.run.model === "score_v3") && !c.fixed && !c.optional && hiddenCols().has(c.key)).length;
  return `<div class="tbl"><table><thead><tr><th></th>${cols.map((c) => th(c)).join("")}<th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted" style="font-size:12px">${visible.length} PL · bấm tiêu đề cột để sắp xếp · ⓘ xem định nghĩa · “Bằng chứng” mở dữ liệu gốc.${hiddenN ? ` · Đang ẩn ${hiddenN} cột` : ""}</p>`;
}
function todosHtml(mine) {
  if (!mine || (mine.error && !mine.todos.length)) return claudeMissing(mine);
  if (!mine.todos.length) return '<div class="empty">Không có to-do.</div>';
  const list = mine.todos.filter((t) => (!S.f.todoSev || t.severity === S.f.todoSev) && (!S.f.todoDue || t.due === S.f.todoDue));
  return `<div class="filters"><select id="f-todo-sev" aria-label="Mức">${opts([["HIGH", "HIGH"], ["MED", "MED"]], S.f.todoSev, "Mọi mức")}</select>
    <select id="f-todo-due" aria-label="Hạn">${opts([["today", "Hôm nay"], ["week", "Trong tuần"]], S.f.todoDue, "Mọi hạn")}</select></div>`
    + (list.length ? list.map((t) => `<div class="todo">${sev(t.severity)}<div><div class="t">${raw(t.title)}</div><div class="d">${raw(t.detail)}</div></div>
    <div class="r"><span class="muted">${t.due === "today" ? "Hôm nay" : "Trong tuần"}</span><span class="acts">${evBtn(t.refs || [])}${fbBtn((t.refs || [])[0] || "todo:" + t.title, "To-do: " + t.title)}</span></div></div>`).join("") : '<div class="empty">Không có to-do khớp bộ lọc.</div>')
    + (mine.dropped ? `<p class="muted" style="font-size:12px">Đã bỏ ${mine.dropped} câu của Claude vì số liệu không khớp dữ liệu.</p>` : "");
}

// ------------------------------------------------------------------ evidence popup
async function openEvidence(units) {
  S.ev = { units, i: 0 };
  $("#ev").classList.add("on");
  await showEvidence();
}
async function showEvidence() {
  const { units, i } = S.ev;
  $("#ev-tabs").innerHTML = units.length > 1 ? units.map((u, k) => `<button class="btn sm ${k === i ? "primary" : ""}" data-evi="${k}">${esc(u.replace(/^camp:\d+:/, "camp: ").replace(/^pl:/, "PL: "))}</button>`).join("") : "";
  $("#ev-title").textContent = "Bằng chứng";
  $("#ev-body").innerHTML = '<div class="muted"><span class="spin"></span> Đang đọc dữ liệu gốc…</div>';
  const ev = await api.evidence(units[i], S.runId);
  if (ev.error) { $("#ev-body").innerHTML = `<div class="empty">${esc(ev.error)}</div>`; return; }
  $("#ev-title").textContent = ev.title;
  const table = (rows) => {
    if (!rows.length) return '<p class="muted">Không có dòng.</p>';
    const cols = Object.keys(rows[0]);
    return `<div class="tbl" style="max-height:240px"><table><thead><tr>${cols.map((c) => `<th>${c === "_row" ? "Dòng Excel" : esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td class="${typeof r[c] === "number" ? "n" : ""}">${esc(typeof r[c] === "number" && c !== "_row" ? Number(r[c]).toLocaleString("en-US", { maximumFractionDigits: 2 }) : r[c])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  };
  $("#ev-body").innerHTML = `
    <p class="muted" style="font-size:12px;margin-top:0">Data đến ${esc(ev.as_of)} · Logic: ${esc(ev.logic_file)} · File: ${esc(Object.values(ev.files || {}).join(", "))}</p>
    <h3>Cách tính</h3>
    <table><tbody>${ev.calc.map((c) => `<tr><td><b>${esc(c.label)}</b></td><td class="muted">${esc(c.formula)}</td><td class="n"><b>${esc(c.value)}</b></td></tr>`).join("")}</tbody></table>
    <h3>Ngưỡng so sánh</h3>
    <table><tbody>${ev.thresholds.map((t) => `<tr><td>${esc(t.label)}</td><td class="num muted">${esc(t.file)} › ${esc(t.cell)}</td><td class="n"><b>${esc(t.value)}</b></td></tr>`).join("")}</tbody></table>
    <h3>Dữ liệu gốc</h3>
    ${ev.sections.map((s) => `<details class="evsec" ${s.key === "raw_mtd" || s.key === "ads_l7d" ? "open" : ""}><summary><b>${esc(s.title)}</b> · <span class="num">${s.row_count}</span> dòng
      ${Object.keys(s.totals).length ? " · " + Object.entries(s.totals).map(([k, v]) => `${esc(k)} = <span class="num">${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>`).join(" · ") : ""}</summary>
      <div class="muted" style="font-size:12px;margin:6px 0">Nguồn: <b>${esc(s.source)}</b><br>Lọc: ${esc(s.filter)}${s.columns_text ? `<br>Cột: ${esc(s.columns_text)}` : ""}${s.row_ranges ? `<br>Dòng Excel: <span class="num">${esc(s.row_ranges.length > 260 ? s.row_ranges.slice(0, s.row_ranges.lastIndexOf(",", 260)) + " … (+" + (s.row_ranges.slice(s.row_ranges.lastIndexOf(",", 260)).split(",").length - 1) + " nhóm dòng)" : s.row_ranges)}</span>` : ""}${s.row_count > s.rows.length ? ` · hiển thị ${s.rows.length}/${s.row_count}` : ""}</div>
      ${table(s.rows)}</details>`).join("")}`;
}
function insightsHtml(mine) {
  const list = !mine || (mine.error && !mine.insights.length) ? claudeMissing(mine)
    : mine.insights.length ? mine.insights.map((i) => `<div class="insight"><span class="ai"><svg class="i" aria-hidden="true"><use href="#spark"/></svg>Claude</span>
      <div>${raw(i.text)}</div><div class="src">${evBtn(i.refs || [])} ${fbBtn((i.refs || [])[0] || "insight", "Insight: " + i.text.slice(0, 60))}</div></div>`).join("")
    : '<div class="empty">Không có insight.</div>';
  const addr = ((S.style || {}).pic_address || {})[S.pic] || {};
  const given = String(S.pic || "").trim().split(/\s+/).pop() || "";
  const opt = (list, cur) => list.map(([v, label]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`).join("");
  return `${list}<h2 style="margin-top:14px">Tin nhắn</h2>
    <div class="grid" style="grid-template-columns:150px 170px 1fr auto;align-items:end;margin-bottom:8px">
      <div><label for="addr-self">Tự xưng</label><select id="addr-self">${opt([["em", "em"], ["anh", "anh"], ["chị", "chị"], ["mình", "mình"], ["tôi", "tôi"], ["", "Không xưng"]], addr.self ?? "em")}</select></div>
      <div><label for="addr-call">Gọi họ là</label><select id="addr-call">${opt([["anh", "anh"], ["chị", "chị"], ["em", "em"], ["bạn", "bạn"], ["name", "Chỉ gọi tên"]], addr.call ?? "chị")}</select></div>
      <div><label for="addr-name">Tên gọi</label><input type="text" id="addr-name" value="${esc(addr.name ?? given)}"></div>
      <button class="btn" id="rewrite"><svg class="i" aria-hidden="true"><use href="#spark"/></svg>Viết lại với Claude</button>
    </div>
    <textarea class="slack-edit" id="slack-text" aria-label="Tin nhắn">${esc(mine ? mine.slack : "")}</textarea>
    <p class="muted" style="font-size:12px;margin:4px 0 0">Xưng hô được lưu riêng cho từng PIC và dùng cho các lần chạy sau.</p>`;
}
async function rewriteMessage() {
  const b = $("#rewrite");
  const addr = { self: $("#addr-self").value, call: $("#addr-call").value, name: $("#addr-name").value.trim() };
  b.disabled = true; b.innerHTML = '<span class="spin"></span> Claude đang viết…';
  const saved = await api.save_pic_address(S.pic, addr);
  if (!bad(saved)) S.style = saved;
  const r = await api.rewrite_message(S.pic, S.runId);
  b.disabled = false; b.innerHTML = '<svg class="i" aria-hidden="true"><use href="#spark"/></svg>Viết lại với Claude';
  if (bad(r)) return;
  S.ai = S.ai || { claude_ok: true, error: null, review: [], per_pic: {} };
  S.ai.per_pic[S.pic] = { insights: [], todos: [], dropped: 0, ...(S.ai.per_pic[S.pic] || {}), slack: r.slack };
  $("#slack-text").value = r.slack;
  S.origSlack = r.slack;
  toast("Đã viết lại tin nhắn.");
}
async function copySlack() {
  const ta = $("#slack-text");
  const text = ta ? ta.value : (aiFor(S.pic) || {}).slack || "";
  if (!text) { toast("Chưa có tin nhắn."); return; }
  copyText(text);
  toast("Đã copy tin nhắn.");
  if (ta && text.trim() !== (S.origSlack || "").trim() && confirm(I18N.t("Lưu bản sửa làm mẫu văn phong?"))) {
    if (!bad(await api.add_style_sample(text))) toast("Đã lưu mẫu văn phong.");
  }
}

// ------------------------------------------------------------------ feedback drawer
function openFb(unit, label) {
  S.fb = { unit, label };
  $("#fbrow").textContent = label;
  $("#fbtxt").value = "";
  $("#fbexp").value = "";
  document.body.classList.add("open");
  $("#fbtxt").focus();
}
function closeFb() { document.body.classList.remove("open"); }
async function sendFb() {
  const issue = $$("#fb-issue button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent).join(", ");
  const item = { unit_id: S.fb.unit, label: S.fb.label, issue, expected: $("#fbexp").value, text: $("#fbtxt").value, run_id: S.runId };
  closeFb();
  toast("Đang gửi góp ý cho Claude phân tích…");
  const r = await api.submit_feedback(item);
  S.feedbackUnits = [...(S.feedbackUnits || []), item.unit_id];
  renderResults();
  if (r.error) { toast(r.error, true); return; }
  toast(r.kind === "lesson" ? "Đã thêm bài học: " + r.lesson_text : r.kind === "param" ? "Có đề xuất sửa tham số – xem Rà soát logic." : "Đã lưu đề xuất rule – xem Rà soát logic.");
}

// ------------------------------------------------------------------ logic review
function bar(b) {
  if (!b) return '<span class="muted">—</span>';
  const add = b.added.HIGH + b.added.MED + b.added.TREND, rem = b.removed.HIGH + b.removed.MED + b.removed.TREND;
  const total = Math.max(add + rem, 1);
  return `<div class="bar" title="thêm ${add} · bỏ ${rem}"><span style="width:${(rem / total) * 100}%;background:var(--ok)"></span><span style="width:${(add / total) * 100}%;background:var(--high)"></span></div>
    <div class="muted num" style="font-size:11px">−${rem} / +${add} alert (HIGH −${b.removed.HIGH} +${b.added.HIGH})</div>`;
}
async function loadReview() {
  const r = await api.review();
  if (bad(r)) return;
  const pending = r.proposals.filter((p) => p.status === "pending");
  const crit = (r.logic_eval?.items || []).filter((x) => x.verdict === "critical").length;
  $("#nav-review").textContent = pending.length + crit; $("#nav-review").classList.toggle("hidden", !(pending.length + crit));
  const findings = r.findings.length ? r.findings.map((f) => `<div class="finding">${sev(f.severity === "INFO" ? "INFO" : f.severity)}<div><b>${raw(f.title)}</b><div class="muted">${raw(f.detail)}</div></div><span class="muted">${f.kind === "param" ? "Tham số" : "Rule mới"}</span></div>`).join("") : '<div class="empty">Chưa có phát hiện (cần chạy với Claude).</div>';
  const fb = r.feedback.slice(-8).reverse();
  const fbHtml = fb.length ? fb.map((f) => `<div class="finding"><span class="sev INFO">${esc(f.status)}</span><div><b>“${raw(f.text || f.issue)}”</b><div class="muted">${esc(f.label || f.unit_id)}</div></div><span class="muted">${esc((f.created || "").slice(0, 10))}</span></div>`).join("") : '<div class="empty">Chưa có góp ý.</div>';
  const props = r.proposals.filter((p) => p.status !== "applied").map((p) => `<tr><td>${esc(p.param_key || "Rule mới")}<div class="muted" style="font-size:12px">${esc(p.title || "")}</div></td>
    <td class="diff">${p.param_key ? `<span class="old">${esc(p.old)}</span> → <span class="new">${esc(p.new)}</span>` : "—"}</td><td class="muted">${esc(p.rationale)}</td>
    <td style="min-width:170px">${bar(p.backtest)}</td>
    <td>${p.status === "saved_rule" ? '<span class="muted">Cần dev</span>' : p.status === "pending"
      ? `<button class="btn sm primary" data-prop="${esc(p.id)}" data-status="approved"><svg class="i" aria-hidden="true"><use href="#check"/></svg>Duyệt</button> <button class="btn sm" data-prop="${esc(p.id)}" data-status="rejected">Bỏ</button>`
      : `${sev(p.status === "approved" ? "OK" : "LOW")} <button class="btn sm ghost" data-prop="${esc(p.id)}" data-status="pending">Hoàn tác</button>`}</td></tr>`).join("");
  const approved = r.proposals.filter((p) => p.status === "approved").length;
  $("#review-body").innerHTML = `${logicCheckHtml(r)}<div class="grid g2"><div><h2>Lỗ hổng phát hiện (lần chạy gần nhất)</h2>${findings}</div><div><h2>Góp ý của bạn</h2>${fbHtml}</div></div>
    <h2 style="margin-top:16px">Đề xuất thay đổi</h2>
    ${props ? `<div class="tbl"><table><thead><tr><th>Tham số</th><th>Thay đổi</th><th>Lý do</th><th>Backtest 4 tuần</th><th></th></tr></thead><tbody>${props}</tbody></table></div>` : '<div class="empty">Chưa có đề xuất.</div>'}
    <div style="display:flex;gap:8px;margin-top:12px;align-items:center"><span class="muted">Đã duyệt: <b class="num">${approved}</b> thay đổi</span><span style="flex:1"></span>
    <button class="btn primary" id="apply" ${approved ? "" : "disabled"}>Tạo phiên bản logic mới & chạy lại</button></div>`;
}

const VERDICT = { critical: ["HIGH", "NGHIÊM TRỌNG"], change: ["MED", "NÊN SỬA"], ignore: ["INFO", "BỎ QUA ĐƯỢC"] };
function logicCheckHtml(r) {
  const ev = r.logic_eval;
  if (!r.logic_issues || !r.logic_issues.length) return r.logic_file ? `<div class="card" style="margin-bottom:12px"><h2 style="margin:0">Kiểm tra file logic</h2><p class="muted" style="margin:6px 0 0">${esc(r.logic_file)}: không có lỗi.</p></div>` : "";
  const unused = r.logic_issues.filter((i) => i.code === "UNUSED");
  const items = (ev?.items || []).map((x) => {
    const [cls, label] = VERDICT[x.verdict] || VERDICT.change, i = x.issue;
    return `<div class="finding"><span class="sev ${cls}">${label}</span><div>
      <b>${esc(i.label || i.key)}</b> <span class="muted num">${esc(i.cell || "chưa có dòng")}</span>
      <div class="muted" style="font-size:12px">${esc(i.message)}${i.value ? ` · giá trị trong file: <code>${esc(i.value)}</code>` : ""}${i.used != null && i.used_from ? ` · đang dùng <b class="num">${esc(i.used)}</b> (${esc(i.used_from)})` : ""}</div>
      <div style="margin-top:4px">${raw(x.reason)}</div>
      ${x.fix ? `<div style="margin-top:4px"><b>Cách sửa:</b> ${esc(x.fix)}${x.suggested_value != null && x.suggested_value !== "" ? ` · gợi ý: <code>${esc(x.suggested_value)}</code>` : ""}</div>` : ""}
    </div><span></span></div>`;
  }).join("");
  return `<div class="card" style="margin-bottom:12px">
    <div style="display:flex;align-items:center;gap:8px"><h2 style="margin:0">Kiểm tra file logic</h2><span class="muted">${esc(r.logic_file || "")}</span><span style="flex:1"></span>
      <span class="ai">${ev?.by_claude ? '<svg class="i" aria-hidden="true"><use href="#spark"/></svg>Claude đánh giá' : "Đánh giá tự động (không có Claude)"}</span></div>
    ${ev?.summary ? `<p style="margin:8px 0">${raw(ev.summary)}</p>` : ""}
    ${items || '<p class="muted">Không có lỗi cần sửa.</p>'}
    ${unused.length ? `<details style="margin-top:8px"><summary class="muted" style="cursor:pointer;font-size:13px">${unused.length} tham số trong file mà app chưa dùng</summary>
      <table style="margin-top:6px"><tbody>${unused.map((i) => `<tr><td>${esc(i.label)}</td><td class="num muted">${esc(i.cell)}</td><td class="n">${esc(i.value ?? "")}</td></tr>`).join("")}</tbody></table></details>` : ""}
  </div>`;
}

// ------------------------------------------------------------------ lessons & history
async function loadLessons() {
  const [l, h] = await Promise.all([api.lessons(), api.history()]);
  if (bad(l) || bad(h)) return;
  $("#f-lessons").textContent = `Bài học: ${l.lessons.length}`;
  $("#lessons-list").innerHTML = l.lessons.length ? l.lessons.map((x, i) => `<div class="check"><span class="sev INFO">#${i + 1}</span><div>${raw(x.text)} <span class="muted">· ${esc((x.created || "").slice(0, 10))}</span></div>
    <button class="btn sm ghost" data-lesson="${esc(x.id)}" aria-label="Xoá bài học" style="margin-left:auto"><svg class="i"><use href="#x"/></svg></button></div>`).join("") : '<div class="empty">Chưa có bài học.</div>';
  $("#versions").innerHTML = h.logic_versions.length ? `<div class="timeline">${h.logic_versions.map((v) => `<div class="ev"><b>Ver ${v.version}</b> ${v.active ? '<span class="sev OK">ĐANG DÙNG</span>' : `<button class="btn sm" data-version="${v.version}">Dùng bản này</button>`}<div class="muted">${esc(v.name)}</div></div>`).join("")}</div>` : '<div class="empty">Chưa có.</div>';
  $("#runs").innerHTML = h.runs.length ? `<table><thead><tr><th>Lần chạy</th><th>Ngày data</th><th>Logic</th><th class="n">Alert</th><th class="n">Góp ý</th></tr></thead><tbody>${h.runs.slice(0, 30).map((r) => `<tr class="expandable" data-run="${esc(r.run_id)}"><td class="num">${esc(r.run_id)}</td><td class="num">${ddmm(r.as_of)}</td><td>Ver ${esc(r.logic_version)}</td><td class="n">${r.alert_count}</td><td class="n">${r.feedback_count}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Chưa có.</div>';
}

// ------------------------------------------------------------------ settings
async function loadSettings() {
  loadRole();
  const [st, set] = await Promise.all([api.get_style(), api.get_settings()]);
  if (bad(st) || bad(set)) return;
  ["language", "pronoun", "length", "tone"].forEach((k) => ($("#st-" + k).value = st[k]));
  $$("#st-emoji button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === st.emoji)));
  $("#st-samples").value = (st.samples || []).join("\n\n");
  $("#st-rules").value = st.rules || "";
  $("#repo").value = set.github_repo || "";
  $("#claude-note").value = set.claude_note || "";
  $("#note-count").textContent = `${(set.claude_note || "").length}/4000 ký tự`;
  $("#mem-limit").value = set.memory_limit_mb ?? 1024;
  $("#mem-auto").checked = set.auto_prune !== false;
  loadMemory();
  $("#auto-upd").checked = !!set.auto_update_check;
  const accounts = (((S.run || {}).inputs || {}).ads || {}).accounts || [];
  $("#ads-account").innerHTML = '<option value="">Tự chọn (account nhiều dòng nhất)</option>' +
    [...new Set([...accounts, set.ads_account].filter(Boolean))].map((a) => `<option ${a === set.ads_account ? "selected" : ""}>${esc(a)}</option>`).join("");
  const m = await api.email_map_suggestions();
  if (!m.error) {
    const opts = (cur) => ['<option value="">—</option>', ...m.pics.map((p) => `<option ${p === cur ? "selected" : ""}>${esc(p)}</option>`)].join("");
    $("#emailmap").innerHTML = `<table class="emailmap"><thead><tr><th>Email</th><th>PIC</th></tr></thead><tbody>${Object.entries(m.email_map).map(([e, p]) => `<tr><td>${esc(e)}</td><td><select data-email="${esc(e)}">${opts(p)}</select></td></tr>`).join("")}</tbody></table>`;
  }
  renderVersion();
}
function bytes(n) {
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(2) + " GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(1) + " MB";
  return Math.max(1, Math.round(n / 1024)) + " KB";
}
const KIND = { runs: "Lịch sử chạy", logic: "Phiên bản logic", lessons: "Bài học", feedback: "Góp ý", proposals: "Đề xuất", other: "Khác" };
function renderMemory(m) {
  const share = Math.min(100, (m.bytes / m.limit_bytes) * 100);
  const color = share > 90 ? "var(--high)" : share > 70 ? "var(--med)" : "var(--primary)";
  const o = m.oldest;
  $("#mem-info").innerHTML = `
    <div style="display:flex;justify-content:space-between;font-size:13px"><b class="num">${bytes(m.bytes)} / ${bytes(m.limit_bytes)}</b><span class="muted num">${share.toFixed(share < 1 ? 2 : 0)}%</span></div>
    <div class="bar" style="height:10px;margin:6px 0" role="progressbar" aria-valuenow="${share.toFixed(0)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${Math.max(share, 0.5)}%;background:${color}"></span></div>
    <div class="muted" style="font-size:12px">${Object.entries(m.by_kind).filter(([, v]) => v).map(([k, v]) => `${KIND[k]}: <span class="num">${bytes(v)}</span>`).join(" · ")}</div>
    <div class="check" style="margin-top:6px"><span class="sev INFO" style="white-space:nowrap">CŨ NHẤT</span><div>${o ? `Lưu ngày <b class="num">${esc(o.date.slice(0, 10).split("-").reverse().join("/"))}</b>${o.as_of ? ` (data đến ${ddmm(o.as_of)})` : ""} · lần chạy ${esc(o.run_id)} · đang giữ ${m.runs} lần chạy` : "Chưa có lần chạy nào"}</div></div>
    ${share > 100 && !m.auto_prune ? '<div class="warnbar">Đã vượt giới hạn – bật “Tự ghi đè” hoặc bấm “Dọn ngay”.</div>' : ""}`;
}
async function loadMemory() { const m = await api.memory_info(); if (!bad(m)) renderMemory(m); }
async function saveStyle() {
  const emoji = ($$("#st-emoji button").find((b) => b.getAttribute("aria-pressed") === "true") || {}).dataset?.v || "low";
  const r = await api.save_style({
    language: $("#st-language").value, pronoun: $("#st-pronoun").value, length: $("#st-length").value, tone: $("#st-tone").value,
    emoji, rules: $("#st-rules").value, samples: $("#st-samples").value.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean),
  });
  if (!bad(r)) toast("Đã lưu văn phong.");
}

// ------------------------------------------------------------------ updates
function renderVersion() {
  const u = S.update;
  const current = u ? u.current : "";
  $("#f-version").innerHTML = u ? `v${esc(current)}${u.newer ? ` · <span style="color:var(--primary)">có bản ${esc(u.latest)}</span>` : ""}` : "";
  $("#ver-checks").innerHTML = u ? `<div class="check"><span class="sev INFO">ĐANG DÙNG</span><span class="num">v${esc(current)}</span></div>
    <div class="check"><span class="sev ${u.newer ? "MED" : "OK"}">${u.newer ? "MỚI" : "MỚI NHẤT"}</span><span class="num">${esc(u.latest || (u.repo ? "không kết nối được GitHub" : "chưa đặt GitHub repo"))}</span><span class="muted">${esc((u.published || "").slice(0, 10))}</span></div>` : "";
}
async function checkUpdate(showModal) {
  const u = await api.check_update();
  if (bad(u)) return;
  S.update = u;
  renderVersion();
  $("#upd-banner").classList.toggle("hidden", !u.newer);
  $("#upd-text").innerHTML = u.newer ? `Có phiên bản mới <b class="num">${esc(u.latest)}</b> (bạn đang dùng <span class="num">v${esc(u.current)}</span>)` : "";
  if (showModal) openWn();
}
function openWn() {
  const u = S.update;
  if (!u || !u.latest) { toast("Chưa có thông tin phiên bản mới."); return; }
  $("#wntitle").textContent = `Có gì mới – ${u.latest}`;
  $("#wn-date").textContent = (u.published || "").slice(0, 10) + " · từ GitHub Release notes";
  $("#wn-notes").innerHTML = md(u.notes);
  $("#wn-prev").innerHTML = u.previous.length ? `<details><summary class="muted" style="cursor:pointer;font-size:13px">Phiên bản trước</summary>${u.previous.map((p) => `<h3>${esc(p.tag)}</h3>${md(p.notes)}`).join("")}</details>` : "";
  $("#wn-install").classList.toggle("hidden", !u.newer);
  $("#wn-stat").textContent = "";
  $("#wn").classList.add("on");
}
function showInstalledNotes(w) {
  S.installedNotes = true;
  $("#wntitle").textContent = `Có gì mới – v${w.version}`;
  $("#wn-date").textContent = (w.date ? w.date + " · " : "") + "bạn vừa cập nhật lên phiên bản này";
  $("#wn-notes").innerHTML = md(w.notes);
  $("#wn-prev").innerHTML = w.previous.length ? `<details><summary class="muted" style="cursor:pointer;font-size:13px">Phiên bản trước</summary>${w.previous.map((p) => `<h3>${esc(p.tag)}</h3>${md(p.notes)}`).join("")}</details>` : "";
  $("#wn-install").classList.add("hidden");
  $("#wn-stat").textContent = "";
  $("#wn").classList.add("on");
}
function closeWn() {
  $("#wn").classList.remove("on");
  if (S.installedNotes) { S.installedNotes = false; api.mark_whats_new_seen(); }
}
async function install() {
  $("#wn-install").disabled = true;
  $("#wn-stat").innerHTML = '<span class="spin"></span> Đang tải và kiểm tra checksum… app sẽ tự đóng và mở lại.';
  const r = await api.install_update();
  $("#wn-install").disabled = false;
  if (r.error) $("#wn-stat").textContent = r.error;
}

// ------------------------------------------------------------------ wiring
function wire() {
  wireDashboard();
  $$("nav button").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  $("#lang").onclick = () => { const l = I18N.lang === "en" ? "vi" : "en"; applyLang(l); store("lang", l); api.save_settings({ ui_lang: l }); if (S.db && $("#dashboard").classList.contains("on")) renderDashboard(); };
  $("#su-lang").onclick = () => $("#lang").click();
  $("#theme").onclick = () => { const t = isDark() ? "light" : "dark"; applyTheme(t); store("theme", t); if (S.db && $("#dashboard").classList.contains("on")) renderDashboard(); };
  $("#cc-recheck").onclick = $("#cc-recheck2").onclick = checkClaude;
  $("#cc-install").onclick = installClaude;
  $("#cc-login").onclick = loginClaude;
  const pillGo = () => { if (S.claudeLevel !== "ok") go("settings"); };
  $("#cc-pill").onclick = pillGo;
  $("#cc-pill").onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") pillGo(); };
  $("#pick").onclick = async () => { const r = await api.pick_folder(); if (!bad(r) && r.paths) useInputs(r.paths); };
  $("#pick-files").onclick = async () => { const r = await api.pick_files(); if (!bad(r) && r.paths) useInputs(r.paths); };
  $("#run-btn").onclick = doRun;
  $("#stop-btn").onclick = stopRun;
  const zone = document.body;
  zone.addEventListener("dragover", (e) => { e.preventDefault(); $("#drop-zone").classList.add("drop"); });
  zone.addEventListener("dragleave", () => $("#drop-zone").classList.remove("drop"));
  // Paths of dropped files arrive from the native handler via window.onDropPaths.
  zone.addEventListener("drop", (e) => { e.preventDefault(); $("#drop-zone").classList.remove("drop"); });
  $("#pic").onchange = (e) => { S.pic = e.target.value; S.open.clear(); renderResults(); };
  $("#copy-slack").onclick = copySlack;
  $("#export").onclick = async () => { if (!S.pic) return; const r = await api.export(S.pic, null, S.runId); if (!bad(r) && r.path) toast("Đã xuất: " + r.path); };
  const pop = $("#colpop");
  const closePop = () => pop.classList.add("hidden");
  pop.addEventListener("click", (e) => {
    if (e.target.closest("[data-closepop]")) closePop();
    const h = e.target.closest("[data-hidecol]");
    if (h) { const set = hiddenCols(); set.add(h.dataset.hidecol); closePop(); setHidden(set); }
    if (e.target.closest("[data-showall]")) { closePop(); setHidden(new Set()); }
  });
  pop.addEventListener("change", (e) => {
    const k = e.target.dataset.togglecol; if (!k) return;
    const set = hiddenCols(); e.target.checked ? set.delete(k) : set.add(k); setHidden(set);
  });
  document.addEventListener("click", (e) => { if (!pop.classList.contains("hidden") && !pop.contains(e.target) && !e.target.closest(".colinfo,#cols-btn")) closePop(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePop(); });
  for (const id of ["#slots-data", "#slots-setting"]) {
    $(id).addEventListener("click", (e) => { const t = e.target.closest("[data-slot]"); if (t) openFileDetail(t.dataset.slot); });
    $(id).addEventListener("keydown", (e) => { const t = e.target.closest("[data-slot]"); if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openFileDetail(t.dataset.slot); } });
  }
  $("#fd-close").onclick = () => $("#fd").classList.remove("on");
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#fd").classList.remove("on"); });
  $("#results-body").addEventListener("click", (e) => {
    const ev = e.target.closest(".evb");
    if (ev) { e.stopPropagation(); openEvidence(ev.dataset.ev.split("|")); return; }
    const fb = e.target.closest(".fb");
    if (fb) { e.stopPropagation(); openFb(fb.dataset.unit, fb.dataset.label); return; }
    const ci = e.target.closest(".colinfo");
    if (ci) { e.stopPropagation(); colInfo(ci); return; }
    if (e.target.closest("#cols-btn")) { colChooser(e.target.closest("#cols-btn")); return; }
    if (e.target.closest("#f-reset")) { S.f = { ...F_DEFAULT }; renderResults(); return; }
    const sortTh = e.target.closest("th[data-sort]");
    if (sortTh) { const k = sortTh.dataset.sort; S.f.dir = S.f.sort === k ? -S.f.dir : 1; S.f.sort = k; renderResults(); return; }
    if (e.target.closest("#rewrite")) { rewriteMessage(); return; }
    const goto = e.target.closest("[data-goto]");
    if (goto) { go(goto.dataset.goto); return; }
    const t = e.target.closest("[data-tab]");
    if (t) { S.tab = t.dataset.tab; renderResults(); return; }
    const row = e.target.closest("tr.expandable[data-pl]");
    if (row) { const pl = row.dataset.pl; S.open.has(pl) ? S.open.delete(pl) : S.open.add(pl); renderResults(); }
  });
  const FMAP = { "f-sev": "sev", "f-action": "action", "f-trend": "trend", "f-status": "status", "f-todo-sev": "todoSev", "f-todo-due": "todoDue" };
  $("#results-body").addEventListener("change", (e) => { if (FMAP[e.target.id]) { S.f[FMAP[e.target.id]] = e.target.value; renderResults(); } });
  $("#results-body").addEventListener("input", (e) => {
    if (e.target.id !== "f-q") return;
    S.f.q = e.target.value;
    clearTimeout(S.qTimer);
    S.qTimer = setTimeout(() => { renderResults(); const el = $("#f-q"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }, 250);
  });
  $$("#fb-issue button, #st-emoji button").forEach((b) => (b.onclick = () => {
    if (b.parentElement.id === "st-emoji") $$("#st-emoji button").forEach((x) => x.setAttribute("aria-pressed", "false"));
    b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
  }));
  $("#fb-close").onclick = $("#fb-cancel").onclick = $("#fb-scrim").onclick = closeFb;
  $("#fb-send").onclick = sendFb;
  $("#review-body").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-prop]");
    if (b) { if (!bad(await api.set_proposal(b.dataset.prop, b.dataset.status))) loadReview(); return; }
    if (e.target.closest("#apply")) {
      e.target.closest("#apply").disabled = true;
      toast("Đang tạo phiên bản logic mới và chạy lại…");
      const r = await api.apply_proposals();
      if (bad(r)) { loadReview(); return; }
      setRun(r); toast(`Đã tạo ${r.logic_file} và chạy lại.`); go("results");
    }
  });
  $("#lessons").addEventListener("click", async (e) => {
    const l = e.target.closest("[data-lesson]");
    if (l && confirm(I18N.t("Xoá bài học này?"))) { if (!bad(await api.delete_lesson(l.dataset.lesson))) loadLessons(); return; }
    const v = e.target.closest("[data-version]");
    if (v) { if (!bad(await api.set_active_logic(Number(v.dataset.version)))) { toast("Đã đổi phiên bản logic – chạy lại để áp dụng."); loadLessons(); } return; }
    const r = e.target.closest("[data-run]");
    if (r) { const run = await api.results(r.dataset.run); if (!bad(run)) { setRun(run); go("results"); } }
  });
  $("#st-save").onclick = saveStyle;
  $("#st-preview-btn").onclick = async () => {
    $("#st-preview").innerHTML = '<span class="spin"></span> Claude đang viết…';
    await saveStyle();
    const r = await api.preview_style();
    $("#st-preview").textContent = r.error ? r.error : r.slack;
  };
  $("#email-save").onclick = async () => {
    const map = {};
    $$("#emailmap select").forEach((s) => { if (s.value) map[s.dataset.email] = s.value; });
    if (!bad(await api.save_settings({ email_map: map }))) toast("Đã lưu email → PIC.");
  };
  $("#repo").onchange = async (e) => { if (!bad(await api.save_settings({ github_repo: e.target.value.trim() }))) checkUpdate(false); };
  $("#auto-upd").onchange = (e) => api.save_settings({ auto_update_check: e.target.checked });
  $("#careful").onchange = (e) => api.save_settings({ careful_mode: e.target.checked });
  $("#claude-note").oninput = (e) => ($("#note-count").textContent = `${e.target.value.length}/4000 ký tự`);
  $("#note-save").onclick = async () => { if (!bad(await api.save_settings({ claude_note: $("#claude-note").value.trim() }))) toast("Đã lưu ghi chú – áp dụng từ lần chạy tới."); };
  $("#mem-save").onclick = async () => {
    const mb = Math.min(1024, Math.max(1, Number($("#mem-limit").value) || 1024));
    $("#mem-limit").value = mb;
    if (!bad(await api.save_settings({ memory_limit_mb: mb, auto_prune: $("#mem-auto").checked }))) { toast("Đã lưu cài đặt bộ nhớ."); loadMemory(); }
  };
  $("#mem-prune").onclick = async () => {
    if (!confirm(I18N.t("Xoá các lần chạy cũ nhất cho tới khi dưới giới hạn?"))) return;
    const r = await api.prune_memory();
    if (!bad(r)) { toast(r.deleted.length ? `Đã xoá ${r.deleted.length} lần chạy cũ.` : "Chưa vượt giới hạn – không cần xoá."); renderMemory(r); }
  };
  $("#ads-account").onchange = async (e) => { if (!bad(await api.save_settings({ ads_account: e.target.value }))) toast("Đã lưu – chạy lại để áp dụng."); };
  $("#upd-check").onclick = () => checkUpdate(true);
  $("#upd-whatsnew").onclick = $("#upd-whatsnew2").onclick = $("#f-version").onclick = openWn;
  $("#upd-now").onclick = () => { openWn(); install(); };
  $("#upd-later").onclick = () => $("#upd-banner").classList.add("hidden");
  $("#wn-close").onclick = $("#wn-later").onclick = closeWn;
  $("#wn").onclick = (e) => { if (e.target.id === "wn") closeWn(); };
  $("#wn-install").onclick = install;
  $("#ev-close").onclick = () => $("#ev").classList.remove("on");
  $("#ev").onclick = (e) => { if (e.target.id === "ev") $("#ev").classList.remove("on"); };
  $("#ev-tabs").onclick = (e) => { const b = e.target.closest("[data-evi]"); if (b) { S.ev.i = Number(b.dataset.evi); showEvidence(); } };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeFb(); closeWn(); $("#ev").classList.remove("on"); } });
}

async function init() {
  api = window.pywebview.api;
  api.get_style().then((st) => { if (!st.error) S.style = st; });
  applyTheme(store("theme"));
  applyLang(store("lang") || "vi");
  wire();
  renderSlots();
  checkClaude();
  const settings = await api.get_settings();
  if (!settings.error) {
    if (settings.ui_lang && settings.ui_lang !== I18N.lang) applyLang(settings.ui_lang);
    if ((settings.last_inputs || {}).paths) useInputs(settings.last_inputs.paths);
    $("#careful").checked = settings.careful_mode !== false;
    if (settings.auto_update_check) checkUpdate(false);
    else api.check_update().then((u) => { if (!u.error) { S.update = u; renderVersion(); } });
  }
  await initTeam();
  if (S.role && S.role.signed_in && S.role.role === "lead" && !S.runId) await loadLastRun();
  const w = await api.whats_new();
  if (!w.error && w.show) showInstalledNotes(w);
  if (S.role && S.role.signed_in && S.role.role === "lead") { loadLessons(); loadReview(); }
}
async function loadLastRun() {
  const last = await api.results();
  if (!last.error && last.result) { setRun(last); go("results"); }
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init);

// ------------------------------------------------------------------ dashboard
// Categorical palette (dataviz reference, validated for this app's light #fff and dark #111A2C cards).
const SERIES = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};
const NO_PIC = "Chưa có PIC";
const charts = {};
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
}
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function picColor(pic, pics) {
  if (pic === NO_PIC) return cssVar("--muted");
  const named = pics.filter((p) => p !== NO_PIC).sort();
  return SERIES[isDark() ? "dark" : "light"][named.indexOf(pic) % 8];  // colour follows the PIC, never its rank
}
function drawChart(id, config) {
  if (charts[id]) charts[id].destroy();
  const el = document.getElementById(id);
  if (!el || !window.Chart) return;
  const ink = cssVar("--muted"), grid = cssVar("--border");
  Chart.defaults.font.family = '"Fira Sans", system-ui, sans-serif';
  Chart.defaults.color = ink;
  config.options = {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: config.type === "line" ? "index" : "nearest", intersect: false },
    plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true } }, ...(config.options?.plugins || {}) },
    scales: Object.fromEntries(Object.entries(config.options?.scales || {}).map(([k, v]) => [k, { grid: { color: grid }, border: { display: false }, ...v }])),
    ...Object.fromEntries(Object.entries(config.options || {}).filter(([k]) => !["plugins", "scales"].includes(k))),
  };
  charts[id] = new Chart(el, config);
}
const FMT = { x: (v) => (num(v) ? Number(v).toFixed(2) + "×" : "—"), "%": (v) => pct(v, 1) };
async function loadDashboard() {
  if (!S.runId) return;
  $("#db-body").innerHTML = '<div class="muted"><span class="spin"></span> Đang tính…</div>';
  const d = await api.dashboard(S.runId);
  if (d.error) { $("#db-body").innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
  S.db = d;
  renderDashboard();
}
function renderDashboard() {
  const d = S.db, sc = d.scorecard, pics = sc.pics.map((p) => p.pic);
  $("#db-sub").textContent = `Data đến ${ddmm(sc.as_of)} · time gone ${pct(sc.time_gone)} · mỗi PIC đo so với target của chính họ; điểm 0–100 là xếp hạng tương đối (100 = tốt nhất).`;
  const ranked = sc.pics.filter((p) => p.rank);
  const metricOpts = sc.metrics.map((m) => `<option value="${m.key}" ${m.key === (S.dbMetric || "gmv_pace") ? "selected" : ""}>${esc(m.label)}</option>`).join("");
  const tr = d.team_review;
  const review = tr ? `${tr.summary ? `<p style="margin-top:0">${raw(tr.summary)}</p>` : ""}
      ${tr.highlights.length ? "<h3 style='font-size:13px;margin:8px 0 4px'>Điểm mạnh</h3>" + tr.highlights.map((h) => `<div class="review-item"><span class="sev OK">${esc(h.pic)}</span> <b>${esc(metricLabel(h.metric))}</b><div>${raw(h.text)}</div></div>`).join("") : ""}
      ${tr.improve.length ? "<h3 style='font-size:13px;margin:12px 0 4px'>Cần cải thiện</h3>" + tr.improve.map((h) => `<div class="review-item"><span class="sev MED">${esc(h.pic)}</span> <b>${esc(metricLabel(h.metric))}</b><div>${raw(h.text)}</div><div class="muted">→ ${raw(h.suggestion)}</div></div>`).join("") : ""}
      <p class="muted" style="font-size:12px">${esc((tr.created || "").replace("T", " "))}${tr.dropped ? ` · đã bỏ ${tr.dropped} câu vì số liệu không khớp` : ""}</p>`
    : '<div class="empty">Bấm “Nhận xét bởi Claude” để Claude so sánh các PIC dựa trên scorecard, xu hướng theo tuần và lịch sử các lần chạy.</div>';
  $("#db-body").innerHTML = `
    <div class="grid g2-1">
      <div class="card"><h2>Xếp hạng tổng (điểm 0–100)</h2><div class="chartbox"><canvas id="ch-rank" role="img" aria-label="Điểm tổng theo PIC"></canvas></div></div>
      <div class="card"><h2>Nhận xét của Claude</h2><div id="db-review">${review}</div></div>
    </div>
    <div class="card" style="margin-top:12px"><h2>Scorecard</h2><div class="tbl"><table>
      <thead><tr><th>#</th><th>PIC</th><th class="n">Điểm</th>${sc.metrics.map((m) => `<th class="n" title="${esc(m.label)}">${esc(m.short)}</th>`).join("")}<th class="n">HIGH</th><th class="n">Excess $</th></tr></thead>
      <tbody>${sc.pics.map((p) => `<tr><td>${p.rank ? `<span class="rank ${p.rank === 1 ? "r1" : ""}">${p.rank}</span>` : "—"}</td>
        <td style="white-space:nowrap"><span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${picColor(p.pic, pics)};margin-right:6px"></span>${esc(p.pic)}</td>
        <td class="n"><b>${p.total ?? "—"}</b></td>
        ${sc.metrics.map((m) => { const s = p.scores[m.key]; return `<td class="n"><div class="scorecell"><span class="num">${FMT[m.fmt](p.values[m.key])}</span>${s == null ? "" : `<span class="scorebar" title="điểm ${s}"><span style="width:${s}%"></span></span>`}</div></td>`; }).join("")}
        <td class="n">${p.values.high_alerts}</td><td class="n">${money(p.values.excess_new)}</td></tr>`).join("")}</tbody></table></div>
      <p class="muted" style="font-size:12px">${sc.metrics.map((m) => `<b>${esc(m.short)}</b>: ${esc(m.label)} (${m.higher_better ? "cao tốt" : "thấp tốt"})`).join(" · ")}<br>Thanh nhỏ = điểm của chỉ số (dài = tốt hơn so với các PIC khác). “${NO_PIC}” không được xếp hạng.</p></div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><h2>Tiến độ GMV & spend so với time gone</h2><div class="chartbox"><canvas id="ch-pace" role="img" aria-label="Tiến độ GMV và spend theo PIC"></canvas></div>
        <p class="muted" style="font-size:12px;margin:4px 0 0">% target tháng đã đạt. Vạch đứt = time gone (${pct(sc.time_gone)}): GMV dưới vạch là chậm, spend vượt vạch là tiêu nhanh.</p></div>
      <div class="card"><h2>Mức cảnh báo theo PIC</h2><div class="chartbox"><canvas id="ch-sev" role="img" aria-label="Số cảnh báo HIGH, MED và cần theo dõi theo PIC"></canvas></div>
        <p class="muted" style="font-size:12px;margin:4px 0 0">PL + campaign. “Theo dõi” = campaign đã action, đang chờ kiểm tra kết quả.</p></div>
    </div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><h2>Bản đồ PL: GMV pace vs spend pace</h2><div class="chartbox tall"><canvas id="ch-plmap" role="img" aria-label="Mỗi chấm là một PL"></canvas></div>
        <p class="muted" style="font-size:12px;margin:4px 0 0">Mỗi chấm là một PL (màu = PIC). Vạch đứt = đúng tiến độ (1×). Góc trên-trái: spend nhanh nhưng GMV chậm – cần xem trước. Góc dưới-phải: GMV tốt, spend còn room.</p></div>
      <div class="card"><h2>Top 10 PL theo excess spend</h2><div class="chartbox tall"><canvas id="ch-excess" role="img" aria-label="Top PL theo excess spend"></canvas></div>
        <p class="muted" style="font-size:12px;margin:4px 0 0">Excess = spend L7D vượt mức hợp lý theo ACoS target, cộng từ các campaign của PL.</p></div>
    </div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><div style="display:flex;gap:8px;align-items:center"><h2 style="margin:0">So sánh theo chỉ số</h2><span style="flex:1"></span><select id="db-metric" style="width:auto">${metricOpts}</select></div>
        <div class="chartbox" style="margin-top:8px"><canvas id="ch-metric" role="img" aria-label="So sánh chỉ số giữa các PIC"></canvas></div></div>
      <div class="card"><div style="display:flex;gap:8px;align-items:center"><h2 style="margin:0">Xu hướng theo tuần</h2><span style="flex:1"></span>
        <select id="db-week" style="width:auto">${[["gmv", "GMV"], ["spend", "Ads spend"], ["tacos", "TACoS"], ["acos", "ACoS"]].map(([v, l]) => `<option value="${v}" ${v === (S.dbWeek || "gmv") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <div class="chartbox" style="margin-top:8px"><canvas id="ch-week" role="img" aria-label="Xu hướng theo tuần"></canvas></div>
        <p class="muted" style="font-size:12px;margin:4px 0 0">Tuần tính từ thứ Hai; tuần cuối có thể chưa đủ 7 ngày.</p></div>
    </div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><h2>Tỷ trọng GMV theo tuần</h2>${pics.filter((p) => p !== NO_PIC).length >= 2 ? '<div class="chartbox"><canvas id="ch-share" role="img" aria-label="Tỷ trọng GMV của từng PIC theo tuần"></canvas></div>' : '<div class="empty">Cần từ 2 PIC trở lên.</div>'}</div>
      <div class="card"><h2>Số alert HIGH qua các lần chạy</h2>${d.runs.length >= 2 ? '<div class="chartbox"><canvas id="ch-runs" role="img" aria-label="Alert HIGH qua các lần chạy"></canvas></div>' : '<div class="empty">Cần ít nhất 2 lần chạy để xem xu hướng.</div>'}</div>
    </div>`;
  drawCharts();
}
function metricLabel(key) { return ((S.db?.scorecard.metrics || []).find((m) => m.key === key) || { label: key }).label; }
function drawCharts() {
  const d = S.db, sc = d.scorecard, pics = sc.pics.map((p) => p.pic);
  const ranked = sc.pics.filter((p) => p.rank);
  const blue = SERIES[isDark() ? "dark" : "light"][0];
  drawChart("ch-rank", { type: "bar", data: { labels: ranked.map((p) => p.pic), datasets: [{ data: ranked.map((p) => p.total), backgroundColor: blue, borderRadius: 4, barThickness: 18 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `Điểm ${c.raw}` } } }, scales: { x: { min: 0, max: 100 }, y: { grid: { display: false } } } } });
  const m = sc.metrics.find((x) => x.key === (S.dbMetric || "gmv_pace"));
  const rows = sc.pics.filter((p) => p.values[m.key] != null);
  drawChart("ch-metric", { type: "bar", data: { labels: rows.map((p) => p.pic), datasets: [{ data: rows.map((p) => p.values[m.key]), backgroundColor: rows.map((p) => picColor(p.pic, pics)), borderRadius: 4, barThickness: 18 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${m.label}: ${FMT[m.fmt](c.raw)}` } } },
      scales: { x: { ticks: { callback: (v) => FMT[m.fmt](v) } }, y: { grid: { display: false } } } } });
  const key = S.dbWeek || "gmv";
  const weeks = [...new Set(d.weekly.map((r) => r.week))].sort();
  const isRatio = key === "tacos" || key === "acos";
  drawChart("ch-week", { type: "line", data: { labels: weeks.map(ddmm), datasets: pics.map((pic) => ({ label: pic, borderColor: picColor(pic, pics), backgroundColor: picColor(pic, pics), borderWidth: 2, pointRadius: 4, tension: 0,
      data: weeks.map((w) => { const r = d.weekly.find((x) => x.pic === pic && x.week === w); return r ? r[key] : null; }) })) },
    options: { plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${isRatio ? pct(c.raw, 1) : money(c.raw)}` } } }, scales: { y: { ticks: { callback: (v) => (isRatio ? pct(v) : "$" + Number(v).toLocaleString("en-US")) } } } } });
  drawExtraCharts(d, sc, pics);
  if (d.runs.length >= 2) {
    drawChart("ch-runs", { type: "line", data: { labels: d.runs.map((r) => `${ddmm(r.as_of)} (${r.run_id.slice(9, 13)})`),
      datasets: pics.map((pic) => ({ label: pic, borderColor: picColor(pic, pics), backgroundColor: picColor(pic, pics), borderWidth: 2, pointRadius: 4, data: d.runs.map((r) => r.by_pic[pic]?.high ?? null) })) },
      options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
  }
}
// Dashed reference lines (time gone, on-pace 1×) drawn under the data.
function refLines(lines) {
  return { id: "ref", beforeDatasetsDraw(chart) {
    const { ctx, chartArea: a, scales } = chart;
    ctx.save(); ctx.setLineDash([5, 4]); ctx.lineWidth = 1.5; ctx.strokeStyle = cssVar("--muted");
    for (const [axis, v] of lines) {
      const sc = scales[axis]; if (!sc || v == null) continue;
      const px = sc.getPixelForValue(v);
      ctx.beginPath();
      if (axis === "x") { ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); } else { ctx.moveTo(a.left, px); ctx.lineTo(a.right, px); }
      ctx.stroke();
    }
    ctx.restore();
  } };
}
function drawExtraCharts(d, sc, pics) {
  const pal = SERIES[isDark() ? "dark" : "light"], surface = cssVar("--card") || (isDark() ? "#111A2C" : "#fff");
  const named = sc.pics.filter((p) => p.pic !== NO_PIC && (p.values.gmv_pct != null || p.values.spend_pct != null));
  drawChart("ch-pace", { type: "bar", plugins: [refLines([["x", sc.time_gone]])],
    data: { labels: named.map((p) => p.pic), datasets: [
      { label: "GMV % target", data: named.map((p) => p.values.gmv_pct), backgroundColor: pal[0], borderRadius: 4, barThickness: 12 },
      { label: "Spend % target", data: named.map((p) => p.values.spend_pct), backgroundColor: pal[1], borderRadius: 4, barThickness: 12 }] },
    options: { indexAxis: "y", plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pct(c.raw, 1)} (time gone ${pct(sc.time_gone)})` } } },
      scales: { x: { beginAtZero: true, suggestedMax: sc.time_gone * 1.2, ticks: { callback: (v) => pct(v) } }, y: { grid: { display: false } } } } });

  const dg = (S.run?.digest || []).filter((x) => x.pic !== NO_PIC);
  const sevSet = [["HIGH", (x) => x.pl_high + x.camp_high, "--high"], ["MED", (x) => x.pl_med + x.camp_med, "--med"], [I18N.t("Theo dõi"), (x) => x.camp_followup, "--info"]];
  drawChart("ch-sev", { type: "bar",
    data: { labels: dg.map((x) => x.pic), datasets: sevSet.map(([label, f, v]) => ({ label, data: dg.map(f), backgroundColor: cssVar(v), borderColor: surface, borderWidth: 1, barThickness: 16 })) },
    options: { indexAxis: "y", scales: { x: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }, y: { stacked: true, grid: { display: false } } } } });

  const pls = (S.run?.pl || []).filter((r) => num(r.gmv_pace) && num(r.spend_pace));
  const cap = (v) => Math.min(v, 3);  // ponytail: extreme paces pinned at 3× so the cloud stays readable; tooltip shows the real value
  const plPics = [...new Set(pls.map((r) => r.pic))];
  drawChart("ch-plmap", { type: "scatter", plugins: [refLines([["x", 1], ["y", 1]])],
    data: { datasets: plPics.map((pic) => ({ label: pic, backgroundColor: picColor(pic, pics), borderColor: surface, borderWidth: 2, pointRadius: 5, pointHoverRadius: 7,
      data: pls.filter((r) => r.pic === pic).map((r) => ({ x: cap(r.gmv_pace), y: cap(r.spend_pace), r })) })) },
    options: { interaction: { mode: "nearest", intersect: true },
      plugins: { tooltip: { callbacks: { label: (c) => { const r = c.raw.r; return `${r.pl} (${r.pic}) · GMV ${Number(r.gmv_pace).toFixed(2)}× · spend ${Number(r.spend_pace).toFixed(2)}× · ${short(r.pacing_action)}`; } } } },
      scales: { x: { min: 0, suggestedMax: 1.5, title: { display: true, text: "GMV pace (× time gone)" } }, y: { min: 0, suggestedMax: 1.5, title: { display: true, text: "Spend pace (× time gone)" } } } } });

  const ex = {};
  (S.run?.camp || []).forEach((c) => { if (c.excess > 0) { const k = c.pl; ex[k] = ex[k] || { pl: c.pl, pic: c.pic, v: 0 }; ex[k].v += c.excess; } });
  const top = Object.values(ex).sort((a, b) => b.v - a.v).slice(0, 10);
  drawChart("ch-excess", { type: "bar",
    data: { labels: top.map((x) => x.pl), datasets: [{ data: top.map((x) => x.v), backgroundColor: top.map((x) => picColor(x.pic, pics)), borderRadius: 4, barThickness: 14 }] },
    options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${top[c.dataIndex].pic}: ${money(c.raw)}` } } },
      scales: { x: { beginAtZero: true, ticks: { callback: (v) => "$" + Number(v).toLocaleString("en-US") } }, y: { grid: { display: false } } } } });
  if (!top.length) { const el = document.getElementById("ch-excess"); if (el) el.parentElement.innerHTML = '<div class="empty">Không có excess spend.</div>'; }

  if (document.getElementById("ch-share")) {
    const weeks = [...new Set(d.weekly.map((r) => r.week))].sort();
    const tot = Object.fromEntries(weeks.map((w) => [w, d.weekly.filter((r) => r.week === w).reduce((a, r) => a + (r.gmv || 0), 0)]));
    drawChart("ch-share", { type: "bar",
      data: { labels: weeks.map(ddmm), datasets: [...pics.filter((p) => p !== NO_PIC), ...(d.weekly.some((r) => r.pic === NO_PIC) ? [NO_PIC] : [])].map((pic) => ({ label: pic, backgroundColor: picColor(pic, pics), borderColor: surface, borderWidth: 1,
        data: weeks.map((w) => { const r = d.weekly.find((x) => x.pic === pic && x.week === w); return r && tot[w] ? r.gmv / tot[w] : 0; }) })) },
      options: { plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pct(c.raw, 1)}` } } },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, min: 0, max: 1, ticks: { callback: (v) => pct(v) } } } } });
  }
}
async function teamReview() {
  const b = $("#db-review-btn");
  b.disabled = true; b.innerHTML = '<span class="spin"></span> Claude đang phân tích…';
  const r = await api.team_review(S.runId);
  b.disabled = false; b.innerHTML = '<svg class="i" aria-hidden="true"><use href="#spark"/></svg>Nhận xét bởi Claude';
  if (bad(r)) return;
  S.db.team_review = r;
  renderDashboard();
}
function renderWeights() {
  const sc = S.db.scorecard;
  $("#db-weights").innerHTML = `<h2>Trọng số điểm</h2><p class="muted" style="font-size:12px;margin-top:0">0 = không tính chỉ số đó. Mặc định mọi chỉ số bằng nhau (1).</p>
    <div class="grid g4">${sc.metrics.map((m) => `<div><label for="w-${m.key}">${esc(m.label)}</label><input type="text" inputmode="decimal" id="w-${m.key}" data-w="${m.key}" value="${sc.weights[m.key] ?? 1}"></div>`).join("")}</div>
    <div style="margin-top:10px;display:flex;gap:8px"><button class="btn primary" id="w-save">Lưu & tính lại</button><button class="btn" id="w-reset">Về mặc định</button></div>`;
}
function wireDashboard() {
  $("#db-review-btn").onclick = teamReview;
  $("#db-weights-btn").onclick = () => { if (!S.db) return; renderWeights(); $("#db-weights").classList.toggle("hidden"); };
  $("#db-weights").addEventListener("click", async (e) => {
    if (e.target.id === "w-save" || e.target.id === "w-reset") {
      const w = {};
      $$("#db-weights [data-w]").forEach((i) => (w[i.dataset.w] = e.target.id === "w-reset" ? 1 : Number(i.value.replace(",", ".")) || 0));
      if (!bad(await api.save_score_weights(w))) { $("#db-weights").classList.add("hidden"); loadDashboard(); }
    }
  });
  $("#db-body").addEventListener("change", (e) => {
    if (e.target.id === "db-metric") { S.dbMetric = e.target.value; drawCharts(); }
    if (e.target.id === "db-week") { S.dbWeek = e.target.value; drawCharts(); }
  });
}

// ------------------------------------------------------------------ team: Supabase sign-in, Lead / Member
S.role = null;
const NOT_SIGNED = "Chưa đăng nhập nhóm";
const STATUS = { ready: ["OK", "ĐÃ ĐĂNG NHẬP"], invited: ["MED", "CHƯA ĐĂNG NHẬP"], disabled: ["INFO", "ĐÃ KHOÁ"] };
function copyBox(id, text) {
  return `<div style="display:flex;gap:6px;align-items:flex-start"><div class="code-box" id="${id}" style="flex:1;white-space:pre-wrap;max-height:220px;overflow:auto" data-no-i18n>${esc(text)}</div><button class="btn sm" data-copy="${id}">Copy</button></div>`;
}
async function loadRole() {
  const r = await api.team_info();
  if (bad(r)) return null;
  S.role = r;
  document.body.classList.toggle("member", r.role === "member");
  document.body.classList.toggle("locked", !r.signed_in);
  $("#role-badge").textContent = !r.signed_in ? NOT_SIGNED : r.role === "lead" ? `Lead · ${r.email}` : `${r.pic || "—"} · chỉ xem`;
  renderTeam();
  return r;
}
function pwChange() {
  return `<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:8px">
    <div><label for="pw-new">Mật khẩu mới (≥ 10 ký tự)</label><input type="password" id="pw-new" autocomplete="new-password"></div>
    <button class="btn" id="pw-save">Đổi mật khẩu</button><button class="btn ghost sm" id="team-signout">Đăng xuất</button></div>`;
}
function showPassword(email, pw, title) {
  $("#mb-pw").innerHTML = `<div class="banner" style="display:block;margin:8px 0"><b>${esc(title)}</b> – gửi riêng cho <span data-no-i18n>${esc(email)}</span>. Mật khẩu chỉ hiện một lần; người đó có thể tự đổi sau khi đăng nhập.
    <div style="margin-top:6px">${copyBox("mb-pw-text", pw)}</div></div>`;
}
function keyHelp() {
  return `<div class="banner" style="margin:8px 0;display:block"><b>Máy này chưa có khoá ký của Lead.</b> Nhập file khoá Lead (đã xuất từ máy cũ) để tải báo cáo lên.
    <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><button class="btn primary sm" id="lk-import">Nhập file khoá Lead…</button>
    <button class="btn ghost sm" id="lk-reset">Mất file khoá? Tạo khoá mới</button></div></div>`;
}
async function renderTeam() {
  const r = S.role || {};
  const el = $("#team-card");
  if (!r.signed_in) {
    el.innerHTML = `<h2>Nhóm</h2><p class="muted" style="margin-top:0">${NOT_SIGNED}. Lead và thành viên đăng nhập bằng email công việc.</p><button class="btn primary" id="team-setup">Đăng nhập nhóm…</button>`;
    return;
  }
  if (r.role === "member") {
    el.innerHTML = `<h2>Nhóm · Thành viên</h2><p style="margin-top:0">${esc(r.name || "")} · <b>${esc(r.email)}</b> · PIC <b>${esc(r.pic || "—")}</b> (chỉ xem)</p>
      ${r.opened ? `<p class="muted" style="font-size:13px">Đang xem ${esc(r.opened.file)}</p>` : ""}${pwChange()}`;
    return;
  }
  el.innerHTML = `<h2>Nhóm · Lead</h2><p style="margin-top:0"><b>${esc(r.email)}</b> · ${esc(r.url)}</p>${r.needs_key ? keyHelp() : ""}
    <h3 style="font-size:14px;margin:12px 0 4px">Tài khoản</h3><div id="mb-table"><div class="muted"><span class="spin"></span></div></div>
    <div class="grid g4" style="margin-top:8px">
      <div><label for="mb-email">Email</label><input type="text" id="mb-email" autocomplete="off"></div>
      <div><label for="mb-name">Tên hiển thị</label><input type="text" id="mb-name"></div>
      <div><label for="mb-pic">PIC</label><input type="text" id="mb-pic" list="mb-pics"><datalist id="mb-pics"></datalist></div>
      <div><label for="mb-role">Vai trò</label><div style="display:flex;gap:6px"><select id="mb-role"><option value="member">Thành viên (chỉ xem PIC)</option><option value="lead">Lead</option></select><button class="btn primary" id="mb-add">Tạo</button></div></div>
    </div>
    <div id="mb-pw"></div>
    <p class="muted" style="font-size:12px">App tạo mật khẩu đầu tiên để bạn gửi cho người đó; không có email nào được gửi. Đổi PIC / khoá tài khoản có hiệu lực ngay; báo cáo tải lên trước khi một người đăng nhập lần đầu sẽ không có phần của họ.</p>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:8px">
      <div><label for="lk-pw">Mật khẩu file khoá (≥ 8 ký tự)</label><input type="password" id="lk-pw" autocomplete="new-password"></div>
      <button class="btn" id="lk-export" ${r.needs_key ? "disabled" : ""}>Xuất khoá Lead…</button>
    </div>${pwChange()}`;
  loadMembers();
}
async function loadMembers() {
  const m = await api.members();
  const box = $("#mb-table");
  if (!box) return;
  if (m.error) { box.innerHTML = `<div class="empty">${esc(m.error)}</div>`; return; }
  const pics = S.run ? [...new Set(S.run.digest.map((d) => d.pic))].filter((p) => p !== NO_PIC) : [];
  $("#mb-pics").innerHTML = [...new Set([...pics, ...m.members.map((x) => x.pic).filter(Boolean)])].map((p) => `<option>${esc(p)}</option>`).join("");
  box.innerHTML = `<div class="tbl"><table><thead><tr><th>Email</th><th>Tên</th><th>Vai trò</th><th>PIC</th><th>Trạng thái</th><th></th></tr></thead><tbody>
    ${m.members.map((x) => `<tr data-email="${esc(x.email)}"><td data-no-i18n>${esc(x.email)}</td><td data-no-i18n>${esc(x.name || "")}</td><td>${x.role === "lead" ? "Lead" : "Thành viên"}</td>
      <td>${x.role === "lead" ? "—" : `<input type="text" class="mb-pic-edit" list="mb-pics" value="${esc(x.pic || "")}" style="width:140px" aria-label="PIC">`}</td>
      <td><span class="sev ${STATUS[x.status][0]}">${STATUS[x.status][1]}</span></td>
      <td style="white-space:nowrap">${x.email === S.role.email ? "" : `<button class="btn sm ghost" data-mb="reset">Đặt lại mật khẩu</button><button class="btn sm ghost" data-mb="toggle" data-active="${x.active ? 1 : 0}">${x.active ? "Khoá" : "Mở khoá"}</button><button class="btn sm ghost" data-mb="delete">Xoá</button>`}</td></tr>`).join("")}
  </tbody></table></div>`;
}
function setupError(msg) {
  $("#setup-error").textContent = msg || "";
  $("#setup-error").classList.toggle("hidden", !msg);
}
function openSetup() {
  const r = S.role || {};
  setupError(r.configured === false ? "App chưa có máy chủ nhóm – cập nhật app lên bản mới nhất." : "");
  $("#su-email").value = r.email || store("lastEmail") || "";
  $("#su-pw").value = "";
  $("#su-ver").textContent = S.update && S.update.current ? `PMKT Alert v${S.update.current}` : "PMKT Alert";
  $("#setup").classList.add("on");
  setTimeout(() => ($("#su-email").value ? $("#su-pw") : $("#su-email")).focus(), 50);
}
function closeSetup() { $("#setup").classList.remove("on"); }
async function signIn(e) {
  if (e) e.preventDefault();
  const email = $("#su-email").value.trim(), pw = $("#su-pw").value;
  if (!email || !pw) { setupError(!email ? "Nhập email." : "Nhập mật khẩu."); (!email ? $("#su-email") : $("#su-pw")).focus(); return; }
  const b = $("#su-signin");
  b.disabled = true; b.innerHTML = '<span class="spin"></span> Đang đăng nhập…';
  setupError("");
  const r = await api.team_sign_in(email, pw);
  b.disabled = false; b.textContent = I18N.t("Đăng nhập");
  if (r.error) { setupError(r.error); $("#su-pw").select(); return; }
  store("lastEmail", email);
  $("#su-pw").value = "";
  closeSetup();
  await loadRole();
  toast(r.role === "lead" ? "Đã đăng nhập – Lead." : `Đã đăng nhập – xem PIC ${r.pic}.`);
  if (r.role === "member") loadReports(true);
  else { loadLastRun(); loadLessons(); loadReview(); }
  if (r.needs_key) { go("settings"); loadSettings(); }
}
async function loadReports(openNewest) {
  const r = await api.list_reports();
  if (r.error) { $("#report-list").innerHTML = `<option value="">${esc(r.error)}</option>`; return; }
  const cur = S.role && S.role.opened ? S.role.opened.file : null;
  $("#report-list").innerHTML = r.reports.length ? r.reports.map((x) => `<option value="${esc(x.name)}" ${x.name === cur ? "selected" : ""}>${esc(x.name.replace("PMKT-Alert_", "").replace("_", " "))}</option>`).join("")
    : "<option value=''>Chưa có báo cáo</option>";
  if (openNewest && r.reports.length && r.reports[0].name !== cur) openReport(r.reports[0].name);
}
async function openReport(name) {
  if (!name) return;
  const r = await api.open_report(name);
  if (bad(r)) return;
  setRun(r);
  await loadRole();
  $("#published-line").textContent = ` · ${r.published_by || "Lead"} tải lên ${(r.published_at || "").replace("T", " ").slice(0, 16)}`;
  go("results");
}
async function uploadReport() {
  const b = $("#upload-btn");
  b.disabled = true;
  const r = await api.upload_report(S.runId);
  b.disabled = false;
  if (bad(r)) return;
  $("#published-line").textContent = ` · đã tải lên ${r.name}`;
  const missing = r.no_readers.filter((p) => p !== NO_PIC);
  toast(`Đã tải lên ${r.name} (${(r.size / 1048576).toFixed(1)} MB) cho ${Object.keys(r.readers).length} PIC.${missing.length ? ` Chưa có tài khoản cho: ${missing.join(", ")}.` : ""}${r.waiting.length ? ` Chưa đăng nhập lần nào: ${r.waiting.join(", ")}.` : ""}`);
}
function wireTeam() {
  $("#role-badge").onclick = () => { if (!(S.role || {}).signed_in) openSetup(); else { go("settings"); loadSettings(); } };
  $("#su-form").addEventListener("submit", signIn);
  $("#su-eye").onclick = () => {
    const show = $("#su-pw").type === "password";
    $("#su-pw").type = show ? "text" : "password";
    $("#su-eye").setAttribute("aria-pressed", String(show));
    $("#su-eye").setAttribute("aria-label", show ? "Ẩn mật khẩu" : "Hiện mật khẩu");
    $("#su-pw").focus();
  };
  const caps = (e) => { if (e.getModifierState) $("#su-caps").classList.toggle("hidden", !e.getModifierState("CapsLock")); };
  $("#su-pw").addEventListener("keydown", caps);
  $("#su-pw").addEventListener("keyup", caps);
  $("#upload-btn").onclick = uploadReport;
  $("#reload-pmkt").onclick = () => loadReports(false);
  $("#report-list").onchange = (e) => openReport(e.target.value);
  $("#open-pmkt").onclick = async () => {
    const f = await api.pick_file("PMKT Alert", "*.pmkt");
    if (bad(f) || !f.path) return;
    const r = await api.open_local_report(f.path);
    if (!bad(r)) { setRun(r); await loadRole(); go("results"); }
  };
  document.addEventListener("change", async (e) => {
    if (!e.target.classList.contains("mb-pic-edit")) return;
    const email = e.target.closest("tr").dataset.email;
    if (!bad(await api.update_member(email, { pic: e.target.value.trim() }))) toast("Đã đổi PIC – có hiệu lực từ báo cáo tải lên tiếp theo.");
  });
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.dataset.copy) { copyText($("#" + t.dataset.copy).textContent); return; }
    if (t.dataset.mb) {
      const row = t.closest("tr"), email = row.dataset.email;
      if (t.dataset.mb === "delete" && confirm(I18N.t("Xoá tài khoản này? Người đó mất quyền xem ngay lập tức."))) { if (!bad(await api.remove_member(email))) loadMembers(); }
      if (t.dataset.mb === "reset" && confirm(I18N.t("Tạo mật khẩu mới cho tài khoản này? Mật khẩu cũ hết hiệu lực."))) {
        const r = await api.reset_password(email);
        if (!bad(r)) showPassword(email, r.password, "Mật khẩu mới");
      }
      if (t.dataset.mb === "toggle") { if (!bad(await api.update_member(email, { active: t.dataset.active !== "1" }))) loadMembers(); }
      return;
    }
    switch (t.id) {
      case "team-setup": openSetup(); break;
      case "team-signout": if (!bad(await api.team_sign_out())) { S.run = null; await loadRole(); openSetup(); } break;
      case "mb-add": {
        const email = $("#mb-email").value.trim();
        const r = await api.add_member(email, $("#mb-name").value.trim(), $("#mb-pic").value.trim(), $("#mb-role").value);
        if (!bad(r)) { ["#mb-email", "#mb-name", "#mb-pic"].forEach((s) => ($(s).value = "")); await loadMembers(); showPassword(email.toLowerCase(), r.password, "Đã tạo tài khoản"); }
        break;
      }
      case "pw-save": {
        const r = await api.team_change_password($("#pw-new").value);
        if (!bad(r)) { $("#pw-new").value = ""; toast("Đã đổi mật khẩu."); }
        break;
      }
      case "lk-export": {
        const r = await api.export_lead_key(null, $("#lk-pw").value);
        if (!bad(r) && !r.cancelled) toast(`Đã lưu ${r.path} – cất giữ cẩn thận.`);
        break;
      }
      case "lk-import": {
        const f = await api.pick_file("Khoá Lead", "*.pmktkey");
        if (bad(f) || !f.path) return;
        const pw = prompt(I18N.t("Mật khẩu file khoá"));
        if (!pw) return;
        if (!bad(await api.import_lead_key(f.path, pw))) { toast("Đã nhập khoá Lead."); loadRole(); }
        break;
      }
      case "lk-reset":
        if (confirm(I18N.t("Tạo khoá ký mới cho nhóm? Các báo cáo đã tải lên trước đây sẽ không mở được nữa.")) && !bad(await api.team_reset_lead_key())) { toast("Đã tạo khoá mới."); loadRole(); }
        break;
    }
  });
}
async function initTeam() {
  wireTeam();
  const r = await loadRole();
  if (!r) return;
  if (!r.signed_in) { openSetup(); return; }  // nothing works before sign-in
  const s = await api.startup_open();
  if (!s.error && s.opened) { const res = await api.results(); if (!res.error) setRun(res); await loadRole(); go("results"); }
  if (r.signed_in && r.role === "member") loadReports(!(s && s.opened));
}

// ------------------------------------------------------------------ Performance Review (logic brief)
const PF_METRICS = [["gmv", "GMV", "money"], ["rs", "RS", "int"], ["spend", "Ads Spend", "money"], ["tacos", "TACOS", "pct"]];
const pfFmt = { money: (v) => money(v), int: (v) => (num(v) ? Math.round(v).toLocaleString("en-US") : "—"), pct: (v) => pct(v, 1) };
function pfAchieve(v, key, gone) {
  if (!num(v)) return '<span class="muted">—</span>';
  // GMV / RS behind the calendar = red; spend / TACoS ahead of it = red (spending faster than planned)
  const bad = key === "gmv" || key === "rs" ? v < gone * 0.9 : v > (key === "tacos" ? 1.1 : gone * 1.1);
  return `<span class="num" style="color:${bad ? "var(--high)" : "var(--fg)"};font-weight:${bad ? 700 : 500}">${pct(v, 1)}</span>`;
}
function pfMetricRows(obj, lead, gone, tail = () => "") {
  return PF_METRICS.map(([k, label, f], i) => `<tr class="${i === 0 ? "grp" : "sub"}">${i === 0 ? lead : ""}<td class="muted">${label}</td>
    <td class="n">${pfFmt[f](obj.target[k])}</td><td class="n">${pfFmt[f](obj.actual[k])}</td><td class="n">${pfAchieve(obj.achieve[k], k, gone)}</td>${i === 0 ? tail() : ""}</tr>`).join("");
}
async function loadPerf(keepFilters) {
  if (!S.runId && !(S.role && S.role.role === "member")) { $("#pf-body").innerHTML = '<div class="empty">Chưa có dữ liệu – chạy dữ liệu trước.</div>'; return; }
  const f = keepFilters ? { pic: $("#pf-pic").value, start: $("#pf-start").value, end: $("#pf-end").value, pl: $("#pf-pl").value } : { pic: S.pfPic || S.pic };
  $("#pf-body").innerHTML = '<div class="muted"><span class="spin"></span> Đang tính…</div>';
  const d = await api.performance(f, S.runId);
  if (d.error) { $("#pf-body").innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
  S.pf = d; S.pfPic = d.filters.pic;
  const ff = d.filters;
  $("#pf-pic").innerHTML = ff.pics.map((p) => `<option ${p === ff.pic ? "selected" : ""}>${esc(p)}</option>`).join("");
  $("#pf-pic").disabled = !!(S.role && S.role.role === "member");
  $("#pf-pl").innerHTML = '<option value="">Tất cả</option>' + ff.pls.map((p) => `<option ${p === ff.pl ? "selected" : ""}>${esc(p)}</option>`).join("");
  for (const [id, v] of [["#pf-start", ff.start], ["#pf-end", ff.end]]) { $(id).value = v; $(id).min = ff.min; $(id).max = ff.max; }
  renderPerf();
}
function renderPerf() {
  const d = S.pf, t = d.summary, gone = t.campaign_gone ?? t.time_gone;
  $("#pf-sub").textContent = `${ddmm(d.filters.start)} – ${ddmm(d.filters.end)}/${d.filters.end.slice(0, 4)} · thực tế theo khung thời gian, target của tháng · PIC ${d.filters.pic || "—"}`;
  const tile = (lbl, val, sub = "") => `<div class="card kpi"><div class="lbl">${lbl}</div><div class="val num">${val}</div>${sub ? `<div class="muted" style="font-size:12px">${sub}</div>` : ""}</div>`;
  const pls = d.pls.map((r) => pfMetricRows(r, `<td rowspan="4"><b>${esc(r.pl)}</b></td>`, gone,
    () => `<td rowspan="4" class="lab" style="color:${actionColor(r.action, r.sev)}">${esc(short(r.action) || "—")}</td><td rowspan="4" class="reason"><div title="${esc(r.reason)}">${esc(r.reason || "—")}</div></td>`)).join("");
  const skus = d.skus.map((r) => pfMetricRows(r, `<td rowspan="4" data-no-i18n><b>${esc(r.sku)}</b><div class="muted" style="font-size:11px">${esc(r.asin)}</div></td>
      <td rowspan="4">${esc(r.pl)}</td><td rowspan="4" style="max-width:220px">${esc(r.product)}</td>
      <td rowspan="4">${r.ineligible.current ? `<span class="sev ${r.ineligible.current.startsWith("INELIGIBLE") ? "HIGH" : "MED"}" data-no-i18n>${esc(r.ineligible.current)}</span>` : '<span class="muted">—</span>'}
        <div class="muted" style="font-size:11px">${r.ineligible.changes} lần đổi · ${r.ineligible.days} ngày ineligible</div></td>
      <td rowspan="4" class="n">${r.stock == null ? "—" : Math.round(r.stock).toLocaleString("en-US")}</td>
      <td rowspan="4">${r.listing_issue ? `<span class="sev MED">${esc(r.listing_issue)}</span>` : '<span class="muted">—</span>'}</td>`, gone)).join("");
  const camps = d.campaigns.map((c) => `<tr><td class="muted" title="${esc(c.campaign)}" style="max-width:320px">${esc(c.campaign)}</td>
      <td class="n">${money(c.spend)}</td><td class="n">${money(c.nmv)}</td><td class="n">${Math.round(c.orders)}</td><td class="n">${pct(c.acos, 1)}</td>
      <td class="n">${signed(c.trend_spend)}</td><td class="n">${signed(c.trend_acos)}</td>
      <td style="white-space:nowrap">${c.last_action ? `${ddmm(String(c.last_action))} <span class="muted">${esc(c.last_action_type)}</span>` : '<span class="muted">—</span>'}</td>
      <td>${c.alert ? `<span class="sev HIGH" title="${esc(c.action)}">YES</span>` : '<span class="muted">No</span>'}</td></tr>`).join("");
  const plNote = d.filters.pl ? ` · lọc theo <b>${esc(d.filters.pl)}</b>` : "";
  $("#pf-body").innerHTML = `
    <div class="grid pf-tiles">
      ${tile("Time gone / Campaign gone", `${pct(t.time_gone)} / ${t.campaign_gone == null ? "—" : pct(t.campaign_gone)}`, "theo tháng của khung thời gian")}
      ${tile("GMV", money(t.gmv), `${pct(t.gmv_pct, 1)} target tháng (${money(t.gmv_target)})`)}
      ${tile("Ads Spend", money(t.spend), `${pct(t.spend_pct, 1)} target tháng (${money(t.spend_target)})`)}
      ${tile("Ads NMV", money(t.ads_nmv))}${tile("ACOS", pct(t.acos, 1))}${tile("TACOS", pct(t.tacos, 1))}${tile("%Ads RS / Total", pct(t.ads_rs_share, 1))}
    </div>
    <div class="card" style="margin-top:12px"><h2>Product line</h2><div class="tbl pf-tbl"><table>
      <thead><tr><th>Product line</th><th>Chỉ số</th><th class="n">Target</th><th class="n">Actual</th><th class="n">%Achieve</th><th>PL action code</th><th>Reason</th></tr></thead>
      <tbody>${pls || '<tr><td colspan="7" class="muted">Không có dữ liệu</td></tr>'}</tbody></table></div>
      <p class="muted" style="font-size:12px;margin:6px 0 0">%Achieve tô đỏ khi GMV/RS chậm hơn ${pct(gone)} (campaign gone) quá 10%, hoặc spend/TACOS vượt mức tương ứng.</p></div>
    <div class="grid g2" style="margin-top:12px">
      <div class="card"><h2>GMV target & actual · Ads NMV · %Ads RS${plNote}</h2><div class="chartbox"><canvas id="pf-c1" role="img" aria-label="GMV theo ngày"></canvas></div></div>
      <div class="card"><h2>Ads Spend target & actual · ACOS${plNote}</h2><div class="chartbox"><canvas id="pf-c2" role="img" aria-label="Ads spend theo ngày"></canvas></div></div>
    </div>
    <div class="card" style="margin-top:12px"><h2>TACOS target & actual${plNote}</h2><div class="chartbox"><canvas id="pf-c3" role="img" aria-label="TACOS theo ngày"></canvas></div></div>
    <div class="card" style="margin-top:12px"><h2>SKU${plNote}</h2><div class="tbl pf-tbl" style="max-height:560px"><table>
      <thead><tr><th>SKU</th><th>Product line</th><th>Product name</th><th>Ineligible status</th><th class="n">Current stock</th><th>Listing issue</th><th>Chỉ số</th><th class="n">Target</th><th class="n">Actual</th><th class="n">%Achieve</th></tr></thead>
      <tbody>${skus || '<tr><td colspan="10" class="muted">Không có SKU</td></tr>'}</tbody></table></div></div>
    <div class="card" style="margin-top:12px"><h2>Campaign${plNote}</h2><div class="tbl" style="max-height:520px"><table>
      <thead><tr><th>Campaign name</th><th class="n">Ads Spend</th><th class="n">Ads NMV</th><th class="n">Ads Order</th><th class="n">ACOS</th><th class="n">Trend Spend L7D</th><th class="n">Trend ACOS L7D</th><th>Last action</th><th>Alert</th></tr></thead>
      <tbody>${camps || '<tr><td colspan="9" class="muted">Không có campaign</td></tr>'}</tbody></table></div></div>`;
  drawPerfCharts();
}
function drawPerfCharts() {
  const d = S.pf.daily, pal = SERIES[isDark() ? "dark" : "light"], grey = cssVar("--muted");
  const labels = d.map((x) => ddmm(x.date));
  const money0 = (v) => "$" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
  const bar = (label, key, color) => ({ type: "bar", label, data: d.map((x) => x[key]), backgroundColor: color, borderRadius: 3, yAxisID: "y", order: 2 });
  const line = (label, key, color, axis, dash) => ({ type: "line", label, data: d.map((x) => x[key]), borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 2, borderDash: dash || [], yAxisID: axis, order: 1, spanGaps: true });
  const pctAxis = { position: "right", grid: { display: false }, ticks: { callback: (v) => pct(v) }, beginAtZero: true };
  const tip = (fmts) => ({ callbacks: { label: (c) => `${c.dataset.label}: ${fmts[c.dataset.yAxisID](c.raw)}` } });
  drawChart("pf-c1", { type: "bar", data: { labels, datasets: [bar(I18N.t("GMV target"), "gmv_target", grey), bar("GMV actual", "gmv", pal[0]), bar("Ads NMV", "ads_nmv", pal[2]), line("%Ads RS / Total RS", "ads_rs_share", pal[1], "y1")] },
    options: { plugins: { tooltip: tip({ y: money, y1: (v) => pct(v, 1) }) }, scales: { y: { beginAtZero: true, ticks: { callback: money0 } }, y1: pctAxis } } });
  drawChart("pf-c2", { type: "bar", data: { labels, datasets: [bar(I18N.t("Ads Spend target"), "spend_target", grey), bar("Ads Spend actual", "spend", pal[1]), line("ACOS", "acos", pal[4], "y1")] },
    options: { plugins: { tooltip: tip({ y: money, y1: (v) => pct(v, 1) }) }, scales: { y: { beginAtZero: true, ticks: { callback: money0 } }, y1: pctAxis } } });
  drawChart("pf-c3", { type: "line", data: { labels, datasets: [line("TACOS target", "tacos_target", grey, "y", [5, 4]), line("TACOS actual", "tacos", pal[0], "y")] },
    options: { plugins: { tooltip: tip({ y: (v) => pct(v, 1) }) }, scales: { y: { beginAtZero: true, ticks: { callback: (v) => pct(v) } } } } });
}
for (const id of ["#pf-pic", "#pf-start", "#pf-end", "#pf-pl"]) {
  document.addEventListener("change", (e) => { if (e.target.matches(id)) { if (id === "#pf-pic") $("#pf-pl").value = ""; loadPerf(true); } });
}
