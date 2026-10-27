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
const ROLE_NAME = { tracker: "Tracking (raw_sso_us, Product Info, KPI)", ads: "Ads by Campaign (ads_camp)", activity: "Activity Log", logic: "Alert_Logic", defind: "Defind" };

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
  if (id === "lessons") loadLessons();
  if (id === "settings") loadSettings();
}
function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; }

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
  if (!confirm(`Cài Claude Code bằng trình cài đặt chính thức của Anthropic?\n\n${cmd}\n\nCần kết nối Internet, mất khoảng 1–2 phút.`)) return;
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
function slot(role) {
  const r = S.roles && S.roles[role];
  return `<div class="slot"><svg class="i" aria-hidden="true"><use href="#file"/></svg><div><div class="name">${esc(r ? r.name : ROLE_NAME[role])}</div>
    <div class="meta">${r ? `${esc(ROLE_NAME[role])} · ${r.size_mb} MB` : "Chưa có file"}</div></div>
    <span class="st sev ${r ? "OK" : "MED"}">${r ? "HỢP LỆ" : "THIẾU"}</span></div>`;
}
function renderSlots() {
  $("#slots-data").innerHTML = ["tracker", "ads", "activity"].map(slot).join("");
  $("#slots-setting").innerHTML = ["logic", "defind"].map(slot).join("");
  $("#run-btn").disabled = !S.roles || ROLES.some((role) => !S.roles[role]);
}
const ROLES = ["tracker", "ads", "activity", "logic", "defind"];
async function useInputs(paths) {
  if (!paths || !paths.length) return;
  // New picks go first so they replace an earlier file of the same role.
  const r = await api.detect([...paths, ...S.paths]);
  if (bad(r)) return;
  S.roles = r.roles;
  S.paths = Object.values(r.roles).map((x) => x.path);
  const msgs = [];
  if (r.missing.length) msgs.push("Còn thiếu: " + r.missing.map((m) => ROLE_NAME[m]).join(", "));
  if (r.unknown.length) msgs.push("Không nhận ra: " + r.unknown.join(", "));
  $("#input-error").textContent = msgs.join(" · ");
  renderSlots();
}
window.onDropPaths = (paths) => { go("run"); useInputs(paths); };
const STEPS = { load: "Đọc & làm sạch data", logic: "Kiểm tra file logic", logic_eval: "Claude đánh giá lỗi file logic", rules: "Tầng 0–4 – Data check · Pacing · Trend · Campaign · Action log", claude: "Claude – Insight · To-do · Tin nhắn · Rà soát logic" };
const STEP_STATE = {};
window.onProgress = (step, state, detail) => {
  STEP_STATE[step] = { state, detail };
  $("#progress").innerHTML = Object.entries(STEP_STATE).map(([k, v]) => {
    const badge = v.state === "running" ? '<span class="spin" aria-label="đang chạy"></span>' : `<span class="sev ${v.state === "done" ? "OK" : "MED"}">${v.state === "done" ? "XONG" : "CẢNH BÁO"}</span>`;
    return `<div class="check">${badge}${esc(STEPS[k] || k)} <span class="muted">— ${esc(v.detail)}</span></div>`;
  }).join("");
};
async function doRun() {
  $("#run-btn").disabled = true;
  Object.keys(STEP_STATE).forEach((k) => delete STEP_STATE[k]);
  window.onProgress("load", "running", "");
  if ($("#use-claude").checked) await checkClaude();
  const r = await api.run(S.paths, $("#as-of").value || null, $("#use-claude").checked);
  $("#run-btn").disabled = false;
  if (r.error) { $("#input-error").textContent = r.error; window.onProgress("load", "warn", r.error); return; }
  setRun(r);
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
  $("#run-meta").innerHTML = `Data đến <span class="num">${ddmm(asOf)}/${asOf.slice(0, 4)}</span> · L7D ${shift(-6)}–${shift(0)} vs P7D ${shift(-13)}–${shift(-7)} · Logic <code>Ver ${S.run.logic_version}</code>`;
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
  const list = (Array.isArray(units) ? units : [units]).filter((u) => /^(pl|camp):/.test(u || ""));
  if (!list.length) return "";
  return `<button class="fb evb" data-ev="${esc(list.join("|"))}" title="Xem dữ liệu gốc: file, sheet, cột, dòng"><svg class="i" aria-hidden="true"><use href="#file"/></svg>${label}</button>`;
}
function opts(list, cur, all) {
  return [`<option value="">${esc(all)}</option>`, ...list.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`)].join("");
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
  </div>`;
}
const SEV_OK = (s, f) => !f || (f === "HM" ? s === "HIGH" || s === "MED" : s === f);
const SORTS = {
  sev: [(r) => SEV[r.pacing_sev ?? r.sev] ?? 3, 1], name: [(r) => (r.pl || r.campaign || "").toLowerCase(), 1],
  gmv: [(r) => r.pct_gmv ?? -1, -1], spend: [(r) => r.pct_spend ?? -1, -1], tacos: [(r) => r.actual_tacos ?? -1, -1],
  dspend: [(r) => r.d_spend ?? -9, -1], excess: [(r) => r._excess ?? r.excess ?? 0, -1],
};
function sortRows(rows) {
  const [key, natural] = SORTS[S.f.sort] || SORTS.sev;
  const dir = natural * S.f.dir;
  return rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * dir || (SEV[a.pacing_sev ?? a.sev] ?? 3) - (SEV[b.pacing_sev ?? b.sev] ?? 3); });
}
function th(label, key, cls = "") {
  const on = S.f.sort === key;
  return `<th class="${cls} sortable" data-sort="${key}" aria-sort="${on ? (S.f.dir === 1 ? "ascending" : "descending") : "none"}">${label}${on ? (S.f.dir === 1 ? " ▾" : " ▴") : ""}</th>`;
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
  const rows = visible.map((p) => {
    const kids = sortRows(byPl[p.pl] || []);
    const open = S.open.has(p.pl) || (q && kids.length);
    const color = p.pacing_sev === "HIGH" ? "var(--high)" : p.pacing_sev === "MED" ? "var(--med)" : "var(--fg)";
    const head = `<tr class="expandable" data-pl="${esc(p.pl)}" aria-expanded="${!!open}"><td>${kids.length ? `<svg class="i" aria-hidden="true" style="transform:rotate(${open ? 90 : 0}deg)"><use href="#chev"/></svg>` : ""}</td>
      <td><b>${esc(p.pl)}</b>${kids.length ? ` <span class="muted">(${kids.length})</span>` : ""}</td><td>${sev(p.pacing_sev)}</td>
      <td class="lab" style="color:${color}">${esc(short(p.pacing_action))}</td><td class="lab">${esc(p.trend_label || "—")}</td>
      <td class="n">${pct(p.pct_gmv)}</td><td class="n">${pct(p.pct_spend)}</td><td class="n">${pct(p.actual_tacos, 1)} <span class="muted">/${pct(p.target_tacos, 1)}</span></td>
      <td class="n">${signed(p.d_spend)}</td><td class="n">${p._excess ? money(p._excess) : "—"}</td>
      <td class="acts">${evBtn(p.unit_id)}${fbBtn(p.unit_id, `${p.pl} · ${short(p.pacing_action)}`, sent.has(p.unit_id))}</td></tr>`;
    const children = open ? kids.map((c) => `<tr class="child"><td></td><td class="muted" title="${esc(c.campaign)}">${esc(c.campaign)}</td><td>${sev(c.sev)}</td>
      <td class="lab">${esc(c.final_label || short(c.base_action))}</td><td class="muted">${esc(c.camp_trend ? c.camp_trend.replace("7D: ", "") : "")}</td><td></td><td></td>
      <td class="n">ACoS ${num(c.acos_ratio) ? Number(c.acos_ratio).toFixed(2) + "×" : "—"}</td><td class="n">${signed(c.d_spend)}</td>
      <td class="n">${money(c.excess)}</td>
      <td class="acts">${evBtn(c.unit_id)}${fbBtn(c.unit_id, `${c.campaign} · ${short(c.final_label || c.base_action)}`, sent.has(c.unit_id))}</td></tr>`).join("") : "";
    return head + children;
  }).join("");
  return `<div class="tbl"><table><thead><tr><th></th>${th("Product Line / Campaign", "name")}${th("Mức", "sev")}<th>Pacing / Action</th><th>Trend L7D</th>
    ${th("GMV %", "gmv", "n")}${th("Spend %", "spend", "n")}${th("TACoS", "tacos", "n")}${th("Δ Spend", "dspend", "n")}${th("Excess $", "excess", "n")}<th></th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted" style="font-size:12px">${visible.length} PL · bấm tiêu đề cột để sắp xếp · “Bằng chứng” mở dữ liệu gốc.</p>`;
}
function todosHtml(mine) {
  if (!mine || (mine.error && !mine.todos.length)) return claudeMissing(mine);
  if (!mine.todos.length) return '<div class="empty">Không có to-do.</div>';
  const list = mine.todos.filter((t) => (!S.f.todoSev || t.severity === S.f.todoSev) && (!S.f.todoDue || t.due === S.f.todoDue));
  return `<div class="filters"><select id="f-todo-sev" aria-label="Mức">${opts([["HIGH", "HIGH"], ["MED", "MED"]], S.f.todoSev, "Mọi mức")}</select>
    <select id="f-todo-due" aria-label="Hạn">${opts([["today", "Hôm nay"], ["week", "Trong tuần"]], S.f.todoDue, "Mọi hạn")}</select></div>`
    + (list.length ? list.map((t) => `<div class="todo">${sev(t.severity)}<div><div class="t">${esc(t.title)}</div><div class="d">${esc(t.detail)}</div></div>
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
      <div>${esc(i.text)}</div><div class="src">${evBtn(i.refs || [])} ${fbBtn((i.refs || [])[0] || "insight", "Insight: " + i.text.slice(0, 60))}</div></div>`).join("")
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
  if (ta && text.trim() !== (S.origSlack || "").trim() && confirm("Lưu bản sửa làm mẫu văn phong?")) {
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
  const findings = r.findings.length ? r.findings.map((f) => `<div class="finding">${sev(f.severity === "INFO" ? "INFO" : f.severity)}<div><b>${esc(f.title)}</b><div class="muted">${esc(f.detail)}</div></div><span class="muted">${f.kind === "param" ? "Tham số" : "Rule mới"}</span></div>`).join("") : '<div class="empty">Chưa có phát hiện (cần chạy với Claude).</div>';
  const fb = r.feedback.slice(-8).reverse();
  const fbHtml = fb.length ? fb.map((f) => `<div class="finding"><span class="sev INFO">${esc(f.status)}</span><div><b>“${esc(f.text || f.issue)}”</b><div class="muted">${esc(f.label || f.unit_id)}</div></div><span class="muted">${esc((f.created || "").slice(0, 10))}</span></div>`).join("") : '<div class="empty">Chưa có góp ý.</div>';
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
      <div style="margin-top:4px">${esc(x.reason)}</div>
      ${x.fix ? `<div style="margin-top:4px"><b>Cách sửa:</b> ${esc(x.fix)}${x.suggested_value != null && x.suggested_value !== "" ? ` · gợi ý: <code>${esc(x.suggested_value)}</code>` : ""}</div>` : ""}
    </div><span></span></div>`;
  }).join("");
  return `<div class="card" style="margin-bottom:12px">
    <div style="display:flex;align-items:center;gap:8px"><h2 style="margin:0">Kiểm tra file logic</h2><span class="muted">${esc(r.logic_file || "")}</span><span style="flex:1"></span>
      <span class="ai">${ev?.by_claude ? '<svg class="i" aria-hidden="true"><use href="#spark"/></svg>Claude đánh giá' : "Đánh giá tự động (không có Claude)"}</span></div>
    ${ev?.summary ? `<p style="margin:8px 0">${esc(ev.summary)}</p>` : ""}
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
  $("#lessons-list").innerHTML = l.lessons.length ? l.lessons.map((x, i) => `<div class="check"><span class="sev INFO">#${i + 1}</span><div>${esc(x.text)} <span class="muted">· ${esc((x.created || "").slice(0, 10))}</span></div>
    <button class="btn sm ghost" data-lesson="${esc(x.id)}" aria-label="Xoá bài học" style="margin-left:auto"><svg class="i"><use href="#x"/></svg></button></div>`).join("") : '<div class="empty">Chưa có bài học.</div>';
  $("#versions").innerHTML = h.logic_versions.length ? `<div class="timeline">${h.logic_versions.map((v) => `<div class="ev"><b>Ver ${v.version}</b> ${v.active ? '<span class="sev OK">ĐANG DÙNG</span>' : `<button class="btn sm" data-version="${v.version}">Dùng bản này</button>`}<div class="muted">${esc(v.name)}</div></div>`).join("")}</div>` : '<div class="empty">Chưa có.</div>';
  $("#runs").innerHTML = h.runs.length ? `<table><thead><tr><th>Lần chạy</th><th>Ngày data</th><th>Logic</th><th class="n">Alert</th><th class="n">Góp ý</th></tr></thead><tbody>${h.runs.slice(0, 30).map((r) => `<tr class="expandable" data-run="${esc(r.run_id)}"><td class="num">${esc(r.run_id)}</td><td class="num">${ddmm(r.as_of)}</td><td>Ver ${esc(r.logic_version)}</td><td class="n">${r.alert_count}</td><td class="n">${r.feedback_count}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">Chưa có.</div>';
}

// ------------------------------------------------------------------ settings
async function loadSettings() {
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
  const zone = document.body;
  zone.addEventListener("dragover", (e) => { e.preventDefault(); $("#drop-zone").classList.add("drop"); });
  zone.addEventListener("dragleave", () => $("#drop-zone").classList.remove("drop"));
  // Paths of dropped files arrive from the native handler via window.onDropPaths.
  zone.addEventListener("drop", (e) => { e.preventDefault(); $("#drop-zone").classList.remove("drop"); });
  $("#pic").onchange = (e) => { S.pic = e.target.value; S.open.clear(); renderResults(); };
  $("#copy-slack").onclick = copySlack;
  $("#export").onclick = async () => { if (!S.pic) return; const r = await api.export(S.pic, null, S.runId); if (!bad(r) && r.path) toast("Đã xuất: " + r.path); };
  $("#results-body").addEventListener("click", (e) => {
    const ev = e.target.closest(".evb");
    if (ev) { e.stopPropagation(); openEvidence(ev.dataset.ev.split("|")); return; }
    const fb = e.target.closest(".fb");
    if (fb) { e.stopPropagation(); openFb(fb.dataset.unit, fb.dataset.label); return; }
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
    if (l && confirm("Xoá bài học này?")) { if (!bad(await api.delete_lesson(l.dataset.lesson))) loadLessons(); return; }
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
    if (!confirm("Xoá các lần chạy cũ nhất cho tới khi dưới giới hạn?")) return;
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
  wire();
  renderSlots();
  checkClaude();
  const settings = await api.get_settings();
  if (!settings.error) {
    if ((settings.last_inputs || {}).paths) useInputs(settings.last_inputs.paths);
    $("#careful").checked = settings.careful_mode !== false;
    if (settings.auto_update_check) checkUpdate(false);
    else api.check_update().then((u) => { if (!u.error) { S.update = u; renderVersion(); } });
  }
  const last = await api.results();
  if (!last.error && last.result) { setRun(last); go("results"); }
  const w = await api.whats_new();
  if (!w.error && w.show) showInstalledNotes(w);
  loadLessons();
  loadReview();
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
  const review = tr ? `${tr.summary ? `<p style="margin-top:0">${esc(tr.summary)}</p>` : ""}
      ${tr.highlights.length ? "<h3 style='font-size:13px;margin:8px 0 4px'>Điểm mạnh</h3>" + tr.highlights.map((h) => `<div class="review-item"><span class="sev OK">${esc(h.pic)}</span> <b>${esc(metricLabel(h.metric))}</b><div>${esc(h.text)}</div></div>`).join("") : ""}
      ${tr.improve.length ? "<h3 style='font-size:13px;margin:12px 0 4px'>Cần cải thiện</h3>" + tr.improve.map((h) => `<div class="review-item"><span class="sev MED">${esc(h.pic)}</span> <b>${esc(metricLabel(h.metric))}</b><div>${esc(h.text)}</div><div class="muted">→ ${esc(h.suggestion)}</div></div>`).join("") : ""}
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
      <div class="card"><div style="display:flex;gap:8px;align-items:center"><h2 style="margin:0">So sánh theo chỉ số</h2><span style="flex:1"></span><select id="db-metric" style="width:auto">${metricOpts}</select></div>
        <div class="chartbox" style="margin-top:8px"><canvas id="ch-metric" role="img" aria-label="So sánh chỉ số giữa các PIC"></canvas></div></div>
      <div class="card"><div style="display:flex;gap:8px;align-items:center"><h2 style="margin:0">Xu hướng theo tuần</h2><span style="flex:1"></span>
        <select id="db-week" style="width:auto">${[["gmv", "GMV"], ["spend", "Ads spend"], ["tacos", "TACoS"], ["acos", "ACoS"]].map(([v, l]) => `<option value="${v}" ${v === (S.dbWeek || "gmv") ? "selected" : ""}>${l}</option>`).join("")}</select></div>
        <div class="chartbox" style="margin-top:8px"><canvas id="ch-week" role="img" aria-label="Xu hướng theo tuần"></canvas></div>
        <p class="muted" style="font-size:12px;margin:4px 0 0">Tuần tính từ thứ Hai; tuần cuối có thể chưa đủ 7 ngày.</p></div>
    </div>
    <div class="card" style="margin-top:12px"><h2>Số alert HIGH qua các lần chạy</h2>${d.runs.length >= 2 ? '<div class="chartbox"><canvas id="ch-runs" role="img" aria-label="Alert HIGH qua các lần chạy"></canvas></div>' : '<div class="empty">Cần ít nhất 2 lần chạy để xem xu hướng.</div>'}</div>`;
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
  if (d.runs.length >= 2) {
    drawChart("ch-runs", { type: "line", data: { labels: d.runs.map((r) => `${ddmm(r.as_of)} (${r.run_id.slice(9, 13)})`),
      datasets: pics.map((pic) => ({ label: pic, borderColor: picColor(pic, pics), backgroundColor: picColor(pic, pics), borderWidth: 2, pointRadius: 4, data: d.runs.map((r) => r.by_pic[pic]?.high ?? null) })) },
      options: { scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
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
