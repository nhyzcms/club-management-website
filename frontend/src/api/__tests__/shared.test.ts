import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EMAIL_DOMAIN_BLOCKED_MESSAGE,
  REASON,
  classifyHttpResponse,
  createRequest,
  getCSRFToken,
  humanizeApiError,
  readResponse,
  setSupersedeHandler,
} from "../shared";

// ---------- classifyHttpResponse：reason 串 → 类型化 kind（唯一映射点） ----------

describe("classifyHttpResponse", () => {
  it("按 reason 映射挤号 / 登录保护 / 限流 / 停用 / 邮箱未验证 / 邮箱后缀白名单", () => {
    expect(classifyHttpResponse(409, { reason: REASON.SESSION_SUPERSEDED, takeover: { device_name: "X" } }))
      .toEqual({ kind: "session_superseded", takeover: { device_name: "X" } });
    expect(classifyHttpResponse(409, { reason: REASON.LOGIN_PROTECTION, retry_after: 120 }))
      .toEqual({ kind: "login_protection", retryAfter: 120 });
    expect(classifyHttpResponse(429, { reason: REASON.LOGIN_THROTTLED }))
      .toEqual({ kind: "login_throttled", retryAfter: 0 });
    expect(classifyHttpResponse(403, { reason: REASON.ACCOUNT_DISABLED }))
      .toEqual({ kind: "account_disabled" });
    expect(classifyHttpResponse(403, { reason: REASON.EMAIL_NOT_VERIFIED, email: "a@b.c" }))
      .toEqual({ kind: "email_not_verified", email: "a@b.c" });
    expect(classifyHttpResponse(400, { reason: REASON.EMAIL_DOMAIN_NOT_ALLOWED, domain: "gmail.com" }))
      .toEqual({ kind: "email_domain_not_allowed", domain: "gmail.com" });
  });

  it("无 reason 时按状态码回退（401 / 403 / 404 / 其余）", () => {
    expect(classifyHttpResponse(401, {})).toEqual({ kind: "auth" });
    expect(classifyHttpResponse(403, {})).toEqual({ kind: "forbidden" });
    expect(classifyHttpResponse(404, {})).toEqual({ kind: "not_found" });
    expect(classifyHttpResponse(500, {})).toEqual({ kind: "http", status: 500 });
  });

  it("挤号缺 takeover 时兜底空对象", () => {
    expect(classifyHttpResponse(409, { reason: REASON.SESSION_SUPERSEDED }))
      .toEqual({ kind: "session_superseded", takeover: {} });
  });

  it("邮箱后缀错误缺 domain 时兜底空串", () => {
    expect(classifyHttpResponse(400, { reason: REASON.EMAIL_DOMAIN_NOT_ALLOWED }))
      .toEqual({ kind: "email_domain_not_allowed", domain: "" });
  });
});

// ---------- readResponse ----------

describe("readResponse", () => {
  const res = (status: number, body?: unknown, jsonThrows = false) =>
    ({
      status,
      ok: status >= 200 && status < 300,
      json: async () => {
        if (jsonThrows) throw new Error("bad json");
        return body;
      },
    }) as unknown as Response;

  it("204 → 成功且数据为 null", async () => {
    expect(await readResponse(res(204))).toEqual({ ok: true, data: null });
  });

  it("2xx JSON → 成功数据", async () => {
    expect(await readResponse(res(200, { a: 1 }))).toEqual({ ok: true, data: { a: 1 } });
  });

  it("非 JSON 响应 → 网络错误", async () => {
    expect(await readResponse(res(502, undefined, true))).toEqual({
      ok: false,
      error: { kind: "network" },
      message: "Failed to fetch",
    });
  });

  it("错误响应 → 类型化错误 + detail / error 文案", async () => {
    expect(await readResponse(res(400, { detail: "标题必填" }))).toMatchObject({
      ok: false,
      error: { kind: "http", status: 400 },
      message: "标题必填",
    });
    expect(await readResponse(res(500, { error: "boom" }))).toMatchObject({
      ok: false,
      message: "boom",
    });
  });
});

// ---------- humanizeApiError ----------

describe("humanizeApiError", () => {
  it("登录保护文案带分钟估算", () => {
    expect(humanizeApiError({ kind: "login_protection", retryAfter: 61 })).toContain("约 2 分钟");
    expect(humanizeApiError({ kind: "login_protection", retryAfter: 0 })).not.toContain("分钟后");
  });

  it("常见 kind 均有中文文案", () => {
    expect(humanizeApiError({ kind: "auth" })).toContain("重新登录");
    expect(humanizeApiError({ kind: "network" })).toContain("网络");
    expect(humanizeApiError({ kind: "http", status: 500 })).toContain("请求失败");
  });

  it("邮箱后缀被拦：逐字回固定文案（与后端一致）", () => {
    expect(humanizeApiError({ kind: "email_domain_not_allowed", domain: "gmail.com" }))
      .toBe(EMAIL_DOMAIN_BLOCKED_MESSAGE);
    expect(EMAIL_DOMAIN_BLOCKED_MESSAGE).toBe(
      "该邮箱后缀暂不可用，请换用其他邮箱。详询社长或服务器管理员",
    );
  });
});

// ---------- getCSRFToken ----------

describe("getCSRFToken", () => {
  afterEach(() => {
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("从 cookie 读取（含 URL 解码）", () => {
    document.cookie = "csrftoken=abc%3D123";
    expect(getCSRFToken()).toBe("abc=123");
  });

  it("缺失时返回空串", () => {
    expect(getCSRFToken()).toBe("");
  });
});

// ---------- createRequest：fetch 适配器 ----------

describe("createRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setSupersedeHandler(null);
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  const okJson = (data: unknown) =>
    ({ status: 200, ok: true, json: async () => data }) as unknown as Response;

  it("拼接 base+path，带 credentials / CSRF / 设备头，JSON 成功返回数据", async () => {
    document.cookie = "csrftoken=tok1";
    const fetchMock = vi.fn(async () => okJson({ hello: "world" }));
    vi.stubGlobal("fetch", fetchMock);

    const request = createRequest("/news");
    const data = await request("/news/1/");
    expect(data).toEqual({ hello: "world" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/news/news/1/");
    expect(init.credentials).toBe("include");
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["X-CSRFToken"]).toBe("tok1");
    expect(typeof headers["X-Device-Id"]).toBe("string");
  });

  it("FormData 请求不设 Content-Type（交给浏览器带 boundary）", async () => {
    const fetchMock = vi.fn(async () => okJson({}));
    vi.stubGlobal("fetch", fetchMock);

    const request = createRequest("/news");
    await request("/news/upload_cover/", { method: "POST", body: new FormData() });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("网络层异常 → Failed to fetch + kind=network", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }));
    const request = createRequest("");
    await expect(request("/x/")).rejects.toMatchObject({
      status: 0,
      apiError: { kind: "network" },
    });
  });

  it("错误响应 → 抛带 status / apiError 的错误；挤号触发已注册的处理器", async () => {
    const fetchMock = vi.fn(async () => ({
      status: 409,
      ok: false,
      json: async () => ({ reason: "session_superseded", takeover: { device_name: "iPad" } }),
    }) as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    const handler = vi.fn();
    setSupersedeHandler(handler);

    const request = createRequest("");
    await expect(request("/x/")).rejects.toMatchObject({
      status: 409,
      apiError: { kind: "session_superseded" },
    });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0]).toMatchObject({
      kind: "session_superseded",
      takeover: { device_name: "iPad" },
    });
  });

  it("邮箱后缀被拦 → 抛 apiError.kind=email_domain_not_allowed（不触发挤号）", async () => {
    const fetchMock = vi.fn(async () => ({
      status: 400,
      ok: false,
      json: async () => ({
        error: EMAIL_DOMAIN_BLOCKED_MESSAGE,
        reason: "email_domain_not_allowed",
        domain: "gmail.com",
      }),
    }) as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    const handler = vi.fn();
    setSupersedeHandler(handler);

    const request = createRequest("/auth");
    await expect(request("/verification/email/bind/", { method: "POST" })).rejects.toMatchObject({
      status: 400,
      apiError: { kind: "email_domain_not_allowed", domain: "gmail.com" },
    });
    expect(handler).not.toHaveBeenCalled();
  });
});
