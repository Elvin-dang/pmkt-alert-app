// pmkt-admin: account management for the Lead. Runs inside Supabase, where the service-role key lives – the app
// never has it. Every call must come from a signed-in, active Lead (checked here against pmkt_members).
//   create        {email, name, role, pic, password}  → member row + login (no email is ever sent)
//   reset_password {email, password}
//   set_active    {email, active}                     → locks/unlocks the login and the data access together
//   delete        {email}

type Env = { url: string; service: string };
type Fetch = typeof fetch;

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const EMAIL = /^[^@\s']+@[^@\s']+\.[^@\s']+$/;
const BAN_FOREVER = "876000h";

export async function handle(req: Request, env: Env, http: Fetch = fetch): Promise<Response> {
  if (req.method !== "POST") return json(405, { error: "POST only" });
  const svc = { apikey: env.service, Authorization: `Bearer ${env.service}`, "Content-Type": "application/json" };
  const call = (path: string, init: RequestInit = {}) =>
    http(env.url + path, { ...init, headers: { ...svc, ...(init.headers || {}) } });
  const row = async (email: string) => {
    const r = await call(`/rest/v1/pmkt_members?select=*&email=eq.${encodeURIComponent(email)}`);
    const rows = r.ok ? await r.json() : [];
    return rows[0] ?? null;
  };

  // who is calling?
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer /, "");
  const me = await http(env.url + "/auth/v1/user", { headers: { apikey: env.service, Authorization: `Bearer ${token}` } });
  if (!me.ok) return json(401, { error: "Phiên đăng nhập không hợp lệ" });
  const caller = String((await me.json()).email || "").toLowerCase();
  const callerRow = await row(caller);
  if (!callerRow || callerRow.role !== "lead" || !callerRow.active) return json(403, { error: "Chỉ Lead được quản lý tài khoản" });

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json(400, { error: "Bad request" });
  }
  const email = String(body.email || "").trim().toLowerCase();
  if (!EMAIL.test(email)) return json(400, { error: "Email không hợp lệ" });
  const password = String(body.password || "");
  if ("password" in body && password.length < 10) return json(400, { error: "Mật khẩu cần ít nhất 10 ký tự" });
  if (email === caller && (body.action === "delete" || body.action === "set_active")) {
    return json(400, { error: "Không thể khoá hoặc xoá chính tài khoản đang dùng" });
  }

  switch (body.action) {
    case "create": {
      const role = body.role === "lead" ? "lead" : "member";
      const pic = role === "member" ? String(body.pic || "").trim() : null;
      if (role === "member" && !pic) return json(400, { error: "Thành viên cần có PIC" });
      if (!("password" in body)) return json(400, { error: "Thiếu mật khẩu" });
      const ins = await call("/rest/v1/pmkt_members", {
        method: "POST",
        body: JSON.stringify({ email, role, pic, name: String(body.name || "").trim() || email }),
      });
      if (!ins.ok) return json(409, { error: "Email này đã có tài khoản" });
      const u = await call("/auth/v1/admin/users", { method: "POST", body: JSON.stringify({ email, password, email_confirm: true }) });
      if (!u.ok) {
        await call(`/rest/v1/pmkt_members?email=eq.${encodeURIComponent(email)}`, { method: "DELETE" });
        return json(400, { error: "Không tạo được đăng nhập: " + ((await u.json()).msg || u.status) });
      }
      const id = (await u.json()).id;
      await call(`/rest/v1/pmkt_members?email=eq.${encodeURIComponent(email)}`, { method: "PATCH", body: JSON.stringify({ user_id: id }) });
      return json(200, { ok: true });
    }
    case "reset_password":
    case "set_active":
    case "delete": {
      const target = await row(email);
      if (!target || !target.user_id) return json(404, { error: "Không tìm thấy tài khoản" });
      const user = `/auth/v1/admin/users/${target.user_id}`;
      if (body.action === "reset_password") {
        if (!("password" in body)) return json(400, { error: "Thiếu mật khẩu" });
        const r = await call(user, { method: "PUT", body: JSON.stringify({ password }) });
        return r.ok ? json(200, { ok: true }) : json(400, { error: "Không đặt lại được mật khẩu" });
      }
      if (body.action === "set_active") {
        const active = body.active === true;
        await call(user, { method: "PUT", body: JSON.stringify({ ban_duration: active ? "none" : BAN_FOREVER }) });
        await call(`/rest/v1/pmkt_members?email=eq.${encodeURIComponent(email)}`, { method: "PATCH", body: JSON.stringify({ active }) });
        return json(200, { ok: true });
      }
      await call(user, { method: "DELETE" });
      await call(`/rest/v1/pmkt_members?email=eq.${encodeURIComponent(email)}`, { method: "DELETE" });
      return json(200, { ok: true });
    }
  }
  return json(400, { error: "Unknown action" });
}

if (import.meta.main) {
  // deno-lint-ignore no-explicit-any
  const env = (globalThis as any).Deno.env;
  // deno-lint-ignore no-explicit-any
  (globalThis as any).Deno.serve((req: Request) =>
    handle(req, { url: env.get("SUPABASE_URL"), service: env.get("SUPABASE_SERVICE_ROLE_KEY") })
  );
}
