import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, deleteJob, reanalyzeJob, reanalyzeUrl } from "./api";

const ID = "0123456789abcdef0123456789abcdef";

function stubFetch(response: Response | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("deleteJob", () => {
  it("sends a DELETE to the job and resolves on 204", async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }));
    await expect(deleteJob(ID)).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/jobs/${ID}`);
    expect(init.method).toBe("DELETE");
  });

  it("rejects with the server's detail on 409", async () => {
    const detail = "job is still at analyzing, wait for it to finish";
    stubFetch(new Response(JSON.stringify({ detail }), { status: 409 }));
    const err = await deleteJob(ID).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe(detail);
    expect((err as ApiError).status).toBe(409);
  });

  it("reports the backend as offline when fetch fails", async () => {
    stubFetch(new TypeError("failed to fetch"));
    const err = await deleteJob(ID).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).offline).toBe(true);
  });

  it("lets an abort through untouched", async () => {
    const abort = new DOMException("aborted", "AbortError");
    stubFetch(abort);
    await expect(deleteJob(ID)).rejects.toBe(abort);
  });
});

describe("reanalyzeUrl", () => {
  it("keeps the edits unless asked to start fresh", () => {
    expect(reanalyzeUrl(ID, "keep")).toBe(`/api/jobs/${ID}/reanalyze`);
    expect(reanalyzeUrl(ID, "fresh")).toBe(`/api/jobs/${ID}/reanalyze?mode=fresh`);
  });

  it("posts to that url", async () => {
    const fetchMock = stubFetch(new Response(JSON.stringify({ job_id: ID }), { status: 202 }));
    await expect(reanalyzeJob(ID, "fresh")).resolves.toEqual({ job_id: ID });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/jobs/${ID}/reanalyze?mode=fresh`);
    expect(init.method).toBe("POST");
  });
});
