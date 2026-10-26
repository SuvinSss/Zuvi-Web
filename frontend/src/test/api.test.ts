import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, messageOf } from "../lib/api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("sends the CSRF header on writes but not reads", async () => {
    document.cookie = "csrftoken=abc123";
    const fn = mockFetch(200, {});
    await api("POST", "/x/", {});
    await api("GET", "/x/");
    const [, post] = fn.mock.calls[0] as [string, { headers: Record<string, string> }];
    const [, read] = fn.mock.calls[1] as [string, { headers: Record<string, string> }];
    expect(post.headers["X-CSRFToken"]).toBe("abc123");
    expect(read.headers["X-CSRFToken"]).toBeUndefined();
  });

  it("turns server errors into ApiError with friendly text", async () => {
    mockFetch(400, { error: { code: "OUT_OF_RANGE", message: "Too far.", retryable: false, fields: { a: ["bad"] } } });
    const err = await api("GET", "/x/").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("OUT_OF_RANGE");
    expect((err as ApiError).fieldMessage("a")).toBe("bad");
  });

  it("handles a non-JSON error page without leaking details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: () => Promise.reject(new Error("x")) }));
    const err = await api("GET", "/x/").catch((e: unknown) => e);
    expect(messageOf(err)).toBe("Something went wrong. Please try again.");
  });

  it("reports network failure as retryable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fail")));
    const err = (await api("GET", "/x/").catch((e: unknown) => e)) as ApiError;
    expect(err.retryable).toBe(true);
    expect(err.status).toBe(0);
  });
});
