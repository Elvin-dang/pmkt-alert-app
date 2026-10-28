// Run: npx deno test supabase/functions/pmkt-admin/  (pytest runs it too when Deno/npx is available)
import { handle } from "./index.ts";

const assert = (ok: unknown, msg = "assertion failed") => {
  if (!ok) throw new Error(msg);
};

type Row = { email: string; role: string; pic: string | null; name: string; active: boolean; user_id?: string };

function backend() {
  const members: Record<string, Row> = {
    "lead@t.test": { email: "lead@t.test", role: "lead", pic: null, name: "Lead", active: true, user_id: "u0" },
    "m@t.test": { email: "m@t.test", role: "member", pic: "PIC A", name: "M", active: true, user_id: "u1" },
  };
  const users: Record<string, { email: string; password?: string; ban?: string }> = {
    u0: { email: "lead@t.test" },
    u1: { email: "m@t.test" },
  };
  const tokens: Record<string, string> = { LEAD: "lead@t.test", MEMBER: "m@t.test" };
  let n = 2;
  const http = async (input: string | URL | Request, init: RequestInit = {}): Promise<Response> => {
    const url = new URL(String(input));
    const h = new Headers(init.headers);
    const body = init.body ? JSON.parse(String(init.body)) : null;
    const res = (s: number, b: unknown) => new Response(JSON.stringify(b), { status: s });
    if (url.pathname === "/auth/v1/user") {
      const email = tokens[(h.get("Authorization") || "").replace("Bearer ", "")];
      return email ? res(200, { email }) : res(401, {});
    }
    assert(h.get("Authorization") === "Bearer SERVICE", "service key must be used for admin/data calls");
    const eq = decodeURIComponent(url.searchParams.get("email") || "").replace("eq.", "");
    if (url.pathname === "/rest/v1/pmkt_members") {
      if (init.method === "POST") {
        if (members[body.email]) return res(409, {});
        members[body.email] = { ...body, active: true };
        return res(201, {});
      }
      if (init.method === "PATCH") Object.assign(members[eq], body);
      if (init.method === "DELETE") delete members[eq];
      return res(200, members[eq] ? [members[eq]] : []);
    }
    if (url.pathname === "/auth/v1/admin/users" && init.method === "POST") {
      if (Object.values(users).some((u) => u.email === body.email)) return res(422, { msg: "already registered" });
      const id = "u" + n++;
      users[id] = { email: body.email, password: body.password };
      return res(200, { id });
    }
    const m = url.pathname.match(/^\/auth\/v1\/admin\/users\/(.+)$/);
    if (m) {
      if (init.method === "DELETE") delete users[m[1]];
      if (init.method === "PUT") {
        if (body.password) users[m[1]].password = body.password;
        if (body.ban_duration) users[m[1]].ban = body.ban_duration;
      }
      return res(200, {});
    }
    return res(404, {});
  };
  const env = { url: "https://p.supabase.co", service: "SERVICE" };
  const call = async (token: string, payload: unknown) => {
    const r = await handle(new Request("https://f/pmkt-admin", {
      method: "POST", headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload),
    }), env, http as typeof fetch);
    return { status: r.status, body: await r.json() };
  };
  return { members, users, call };
}

Deno.test("lead creates a PIC account with a login, no email sent", async () => {
  const b = backend();
  const r = await b.call("LEAD", { action: "create", email: "New@T.test", name: "N", role: "member", pic: "PIC B", password: "abcdefghij" });
  assert(r.status === 200, JSON.stringify(r));
  const row = b.members["new@t.test"];
  assert(row && row.pic === "PIC B" && row.user_id, "row with user_id");
  assert(b.users[row.user_id!].password === "abcdefghij", "login created");
});

Deno.test("only an active lead may call", async () => {
  const b = backend();
  assert((await b.call("MEMBER", { action: "create", email: "x@t.test", role: "lead", password: "abcdefghij" })).status === 403);
  assert((await b.call("NOPE", { action: "delete", email: "m@t.test" })).status === 401);
  b.members["lead@t.test"].active = false;
  assert((await b.call("LEAD", { action: "delete", email: "m@t.test" })).status === 403);
  assert(b.members["m@t.test"], "nothing deleted");
});

Deno.test("validation", async () => {
  const b = backend();
  assert((await b.call("LEAD", { action: "create", email: "bad", role: "member", pic: "A", password: "abcdefghij" })).status === 400);
  assert((await b.call("LEAD", { action: "create", email: "a@t.test", role: "member", password: "abcdefghij" })).status === 400);
  assert((await b.call("LEAD", { action: "create", email: "a@t.test", role: "member", pic: "A", password: "short" })).status === 400);
  assert((await b.call("LEAD", { action: "create", email: "m@t.test", role: "member", pic: "A", password: "abcdefghij" })).status === 409);
  assert((await b.call("LEAD", { action: "delete", email: "lead@t.test" })).status === 400, "cannot delete self");
  assert((await b.call("LEAD", { action: "set_active", email: "lead@t.test", active: false })).status === 400, "cannot lock self");
});

Deno.test("failed login creation rolls back the member row", async () => {
  const b = backend();
  b.users["u9"] = { email: "dup@t.test" };
  const r = await b.call("LEAD", { action: "create", email: "dup@t.test", role: "member", pic: "A", password: "abcdefghij" });
  assert(r.status === 400 && !b.members["dup@t.test"], JSON.stringify(r));
});

Deno.test("reset, lock/unlock, delete", async () => {
  const b = backend();
  assert((await b.call("LEAD", { action: "reset_password", email: "m@t.test", password: "newpassword1" })).status === 200);
  assert(b.users.u1.password === "newpassword1");
  await b.call("LEAD", { action: "set_active", email: "m@t.test", active: false });
  assert(!b.members["m@t.test"].active && b.users.u1.ban === "876000h", "locked in both places");
  await b.call("LEAD", { action: "set_active", email: "m@t.test", active: true });
  assert(b.members["m@t.test"].active && b.users.u1.ban === "none");
  await b.call("LEAD", { action: "delete", email: "m@t.test" });
  assert(!b.members["m@t.test"] && !b.users.u1, "row and login deleted");
});
