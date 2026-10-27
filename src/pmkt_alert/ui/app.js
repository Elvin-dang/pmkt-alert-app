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
const S = { paths: [], roles: null, run: null, ai: null, runId: null, pic: null, showLow: false, open: new Set(), update: null, fb: null, origSlack: "" };

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
const STEPS = { load: "Đọc & làm sạch data", rules: "Tầng 0–4 – Data check · Pacing · Trend · Campaign · Action log", claude: "Claude – Insight · To-do · Tin nhắn · Rà soát logic" };
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
  S.run = r.result; S.ai = r.ai; S.runId = r.run_id; S.open.clear();
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
    <div class="grid g5" style="margin-top:12px">
      <div class="card kpi"><div class="lbl">PL HIGH (pacing)</div><div class="val high num">${d.pl_high}</div></div>
      <div class="card kpi"><div class="lbl">PL MED (pacing)</div><div class="val med num">${d.pl_med}</div></div>
      <div class="card kpi"><div class="lbl">PL trend cần review</div><div class="val num">${d.pl_trend_review}</div></div>
      <div class="card kpi"><div class="lbl">Camp HIGH / MED · follow-up</div><div class="val num"><span style="color:var(--high)">${d.camp_high}</span> / <span style="color:var(--med)">${d.camp_med}</span> · ${d.camp_followup}</div></div>
      <div class="card kpi"><div class="lbl">Excess spend cần action</div><div class="val num">${money(d.excess_new)}</div></div>
    </div>
    <div class="tabs" role="tablist">
      ${[["t-alerts", "Cảnh báo"], ["t-todos", `To-do (${todos.length})`], ["t-insights", "Insight & Slack"], ["t-data", `Data ⚠ (${issues.length})`]]
        .map(([id, label]) => `<button role="tab" aria-selected="${id === tab}" data-tab="${id}">${label}</button>`).join("")}
      <span style="flex:1"></span>
      <label style="display:flex;gap:6px;align-items:center;margin:0;font-weight:500;color:var(--fg)"><input type="checkbox" id="show-low" ${S.showLow ? "checked" : ""}> Hiện LOW</label>
    </div>
    <div class="tabpanel ${tab === "t-alerts" ? "on" : ""}" id="t-alerts">${alertsTable()}</div>
    <div class="tabpanel ${tab === "t-todos" ? "on" : ""}" id="t-todos">${todosHtml(mine)}</div>
    <div class="tabpanel ${tab === "t-insights" ? "on" : ""}" id="t-insights">${insightsHtml(mine)}</div>
    <div class="tabpanel ${tab === "t-data" ? "on" : ""}" id="t-data">${issues.length ? issues.map((i) => `<div class="todo"><span class="sev ${i.severity === "WARN" ? "MED" : "INFO"}">${i.severity === "WARN" ? "DATA" : "INFO"}</span><div><div class="t">${esc(i.title)}</div><div class="d">${esc(i.detail)}</div></div></div>`).join("") : '<div class="empty">Data ổn.</div>'}</div>`;
  S.origSlack = mine ? mine.slack : "";
}
function claudeMissing(mine) {
  const err = !S.ai ? "Lần chạy này không dùng Claude" : (mine && mine.error) || S.ai.error;
  return `<div class="empty"><b>Claude không sẵn sàng</b><br>${esc(err || "")}<br>Kết quả rule vẫn đầy đủ ở tab Cảnh báo.</div>`;
}
function alertsTable() {
  const pls = S.run.pl.filter((r) => r.pic === S.pic);
  const camps = S.run.camp.filter((r) => r.pic === S.pic && (S.showLow || r.sev === "HIGH" || r.sev === "MED"));
  const byPl = {};
  camps.forEach((c) => (byPl[c.pl] = byPl[c.pl] || []).push(c));
  const visible = pls.filter((p) => S.showLow || p.pacing_sev !== "LOW" || p.trend_label || byPl[p.pl])
    .sort((a, b) => SEV[a.pacing_sev] - SEV[b.pacing_sev] || (b.spend_mtd || 0) - (a.spend_mtd || 0));
  if (!visible.length) return '<div class="empty">Không có cảnh báo cho PIC này.</div>';
  const sent = new Set((S.feedbackUnits || []));
  const rows = visible.map((p) => {
    const kids = (byPl[p.pl] || []).sort((a, b) => SEV[a.sev] - SEV[b.sev] || b.excess - a.excess);
    const open = S.open.has(p.pl);
    const color = p.pacing_sev === "HIGH" ? "var(--high)" : p.pacing_sev === "MED" ? "var(--med)" : "var(--fg)";
    const head = `<tr class="expandable" data-pl="${esc(p.pl)}" aria-expanded="${open}"><td>${kids.length ? `<svg class="i" aria-hidden="true" style="transform:rotate(${open ? 90 : 0}deg)"><use href="#chev"/></svg>` : ""}</td>
      <td><b>${esc(p.pl)}</b>${kids.length ? ` <span class="muted">(${kids.length})</span>` : ""}</td><td>${sev(p.pacing_sev)}</td>
      <td class="lab" style="color:${color}">${esc(short(p.pacing_action))}</td><td class="lab">${esc(p.trend_label || "—")}</td>
      <td class="n">${pct(p.pct_gmv)}</td><td class="n">${pct(p.pct_spend)}</td><td class="n">${pct(p.actual_tacos, 1)} <span class="muted">/${pct(p.target_tacos, 1)}</span></td>
      <td class="n">${signed(p.d_spend)}</td><td class="n">—</td><td class="muted">${esc(p.pacing_reason)}${p.trend_action ? "<br>" + esc(p.trend_action) : ""}</td>
      <td>${fbBtn(p.unit_id, `${p.pl} · ${short(p.pacing_action)}`, sent.has(p.unit_id))}</td></tr>`;
    const children = open ? kids.map((c) => `<tr class="child"><td></td><td class="muted" title="${esc(c.campaign)}">${esc(c.campaign)}</td><td>${sev(c.sev)}</td>
      <td class="lab">${esc(c.final_label || short(c.base_action))}</td><td></td><td></td><td></td>
      <td class="n">ACoS ${num(c.acos_ratio) ? Number(c.acos_ratio).toFixed(2) + "×" : "—"}</td><td class="n">${signed(c.d_spend)}</td>
      <td class="n">${money(c.excess)}</td><td class="muted">${esc([c.camp_trend, c.followup_check].filter(Boolean).join(" · "))}</td>
      <td>${fbBtn(c.unit_id, `${c.campaign} · ${short(c.final_label || c.base_action)}`, sent.has(c.unit_id))}</td></tr>`).join("") : "";
    return head + children;
  }).join("");
  return `<div class="tbl"><table><thead><tr><th></th><th>Product Line / Campaign</th><th>Mức</th><th>Pacing / Action</th><th>Trend L7D</th>
    <th class="n">GMV %</th><th class="n">Spend %</th><th class="n">TACoS</th><th class="n">Δ Spend</th><th class="n">Excess $</th><th>Lý do</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function todosHtml(mine) {
  if (!mine || (mine.error && !mine.todos.length)) return claudeMissing(mine);
  if (!mine.todos.length) return '<div class="empty">Không có to-do.</div>';
  return mine.todos.map((t) => `<div class="todo">${sev(t.severity)}<div><div class="t">${esc(t.title)}</div><div class="d">${esc(t.detail)}</div></div>
    <div class="r"><span class="muted">${t.due === "today" ? "Hôm nay" : "Trong tuần"}</span>${fbBtn((t.refs || [])[0] || "todo:" + t.title, "To-do: " + t.title)}</div></div>`).join("")
    + (mine.dropped ? `<p class="muted" style="font-size:12px">Đã bỏ ${mine.dropped} câu của Claude vì số liệu không khớp dữ liệu.</p>` : "");
}
function insightsHtml(mine) {
  const list = !mine || (mine.error && !mine.insights.length) ? claudeMissing(mine)
    : mine.insights.length ? mine.insights.map((i) => `<div class="insight"><span class="ai"><svg class="i" aria-hidden="true"><use href="#spark"/></svg>Claude</span>
      <div>${esc(i.text)}</div><div class="src">Nguồn: ${esc((i.refs || []).join(", "))} ${fbBtn((i.refs || [])[0] || "insight", "Insight: " + i.text.slice(0, 60))}</div></div>`).join("")
    : '<div class="empty">Không có insight.</div>';
  return `${list}<h2 style="margin-top:14px">Tin nhắn Slack</h2>
    <textarea class="slack-edit" id="slack-text" aria-label="Tin nhắn Slack">${esc(mine ? mine.slack : "")}</textarea>`;
}
async function copySlack() {
  const ta = $("#slack-text");
  const text = ta ? ta.value : (aiFor(S.pic) || {}).slack || "";
  if (!text) { toast("Chưa có tin nhắn."); return; }
  copyText(text);
  toast("Đã copy tin nhắn Slack.");
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
  $("#nav-review").textContent = pending.length; $("#nav-review").classList.toggle("hidden", !pending.length);
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
  $("#review-body").innerHTML = `<div class="grid g2"><div><h2>Lỗ hổng phát hiện (lần chạy gần nhất)</h2>${findings}</div><div><h2>Góp ý của bạn</h2>${fbHtml}</div></div>
    <h2 style="margin-top:16px">Đề xuất thay đổi</h2>
    ${props ? `<div class="tbl"><table><thead><tr><th>Tham số</th><th>Thay đổi</th><th>Lý do</th><th>Backtest 4 tuần</th><th></th></tr></thead><tbody>${props}</tbody></table></div>` : '<div class="empty">Chưa có đề xuất.</div>'}
    <div style="display:flex;gap:8px;margin-top:12px;align-items:center"><span class="muted">Đã duyệt: <b class="num">${approved}</b> thay đổi</span><span style="flex:1"></span>
    <button class="btn primary" id="apply" ${approved ? "" : "disabled"}>Tạo phiên bản logic mới & chạy lại</button></div>`;
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
async function install() {
  $("#wn-install").disabled = true;
  $("#wn-stat").innerHTML = '<span class="spin"></span> Đang tải và kiểm tra checksum… app sẽ tự đóng và mở lại.';
  const r = await api.install_update();
  $("#wn-install").disabled = false;
  if (r.error) $("#wn-stat").textContent = r.error;
}

// ------------------------------------------------------------------ wiring
function wire() {
  $$("nav button").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  $("#theme").onclick = () => { const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; applyTheme(t); store("theme", t); };
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
    const fb = e.target.closest(".fb");
    if (fb) { e.stopPropagation(); openFb(fb.dataset.unit, fb.dataset.label); return; }
    const t = e.target.closest("[data-tab]");
    if (t) { S.tab = t.dataset.tab; renderResults(); return; }
    const row = e.target.closest("tr.expandable[data-pl]");
    if (row) { const pl = row.dataset.pl; S.open.has(pl) ? S.open.delete(pl) : S.open.add(pl); renderResults(); }
  });
  $("#results-body").addEventListener("change", (e) => { if (e.target.id === "show-low") { S.showLow = e.target.checked; renderResults(); } });
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
  $("#ads-account").onchange = async (e) => { if (!bad(await api.save_settings({ ads_account: e.target.value }))) toast("Đã lưu – chạy lại để áp dụng."); };
  $("#upd-check").onclick = () => checkUpdate(true);
  $("#upd-whatsnew").onclick = $("#upd-whatsnew2").onclick = $("#f-version").onclick = openWn;
  $("#upd-now").onclick = () => { openWn(); install(); };
  $("#upd-later").onclick = () => $("#upd-banner").classList.add("hidden");
  $("#wn-close").onclick = $("#wn-later").onclick = () => $("#wn").classList.remove("on");
  $("#wn").onclick = (e) => { if (e.target.id === "wn") $("#wn").classList.remove("on"); };
  $("#wn-install").onclick = install;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeFb(); $("#wn").classList.remove("on"); } });
}

async function init() {
  api = window.pywebview.api;
  applyTheme(store("theme"));
  wire();
  renderSlots();
  checkClaude();
  const settings = await api.get_settings();
  if (!settings.error) {
    if ((settings.last_inputs || {}).paths) useInputs(settings.last_inputs.paths);
    if (settings.auto_update_check) checkUpdate(false);
    else api.check_update().then((u) => { if (!u.error) { S.update = u; renderVersion(); } });
  }
  const last = await api.results();
  if (!last.error && last.result) { setRun(last); go("results"); }
  loadLessons();
  loadReview();
}

if (window.pywebview && window.pywebview.api) init();
else window.addEventListener("pywebviewready", init);
