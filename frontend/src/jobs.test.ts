import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fileSha256,
  formatEditCount,
  formatJobDate,
  groupJobs,
  JOB_PARAM,
  jobIdFromSearch,
  searchWithJob,
} from "./jobs";
import type { JobSummary } from "./types/api";

const ID = "0123456789abcdef0123456789abcdef";
const OTHER_ID = "fedcba9876543210fedcba9876543210";

function job(jobId: string, sha256: string, overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: jobId,
    filename: "song.wav",
    sha256,
    size_bytes: 1000,
    created_at: "2026-03-02T10:15:30+00:00",
    reanalyzed_at: null,
    status: "done",
    edits: null,
    demo: false,
    ...overrides,
  };
}

describe("JOB_PARAM", () => {
  it("is the query key the helpers read and write", () => {
    expect(JOB_PARAM).toBe("job");
  });
});

describe("jobIdFromSearch", () => {
  it("reads the job param", () => {
    expect(jobIdFromSearch(`?job=${ID}`)).toBe(ID);
  });

  it("finds it among other params and without the leading question mark", () => {
    expect(jobIdFromSearch(`?a=1&job=${ID}&b=2`)).toBe(ID);
    expect(jobIdFromSearch(`job=${ID}`)).toBe(ID);
  });

  it("is null when the param is missing or the search is empty", () => {
    expect(jobIdFromSearch("")).toBeNull();
    expect(jobIdFromSearch("?")).toBeNull();
    expect(jobIdFromSearch("?other=1")).toBeNull();
    expect(jobIdFromSearch("?job=")).toBeNull();
  });

  it("rejects anything that isn't 32 lowercase hex characters", () => {
    expect(jobIdFromSearch("?job=abc")).toBeNull();
    expect(jobIdFromSearch(`?job=${ID}0`)).toBeNull();
    expect(jobIdFromSearch(`?job=${ID.slice(1)}`)).toBeNull();
    expect(jobIdFromSearch(`?job=${ID.toUpperCase()}`)).toBeNull();
    expect(jobIdFromSearch(`?job=${"g".repeat(32)}`)).toBeNull();
    expect(jobIdFromSearch(`?job=${ID}%0A`)).toBeNull();
    expect(jobIdFromSearch(`?job=../${"a".repeat(29)}`)).toBeNull();
  });
});

describe("searchWithJob", () => {
  it("sets the param on an empty search", () => {
    expect(searchWithJob("", ID)).toBe(`?job=${ID}`);
    expect(searchWithJob("?", ID)).toBe(`?job=${ID}`);
  });

  it("replaces an existing job and keeps the other params", () => {
    expect(searchWithJob(`?a=1&job=${ID}&b=2`, OTHER_ID)).toBe(`?a=1&job=${OTHER_ID}&b=2`);
  });

  it("removes the param and keeps what is left", () => {
    expect(searchWithJob(`?a=1&job=${ID}`, null)).toBe("?a=1");
  });

  it("returns an empty string when nothing is left", () => {
    expect(searchWithJob(`?job=${ID}`, null)).toBe("");
    expect(searchWithJob("", null)).toBe("");
    expect(searchWithJob("?", null)).toBe("");
  });

  it("leaves a search without a job alone when asked to remove one", () => {
    expect(searchWithJob("?a=1", null)).toBe("?a=1");
  });

  it("round-trips through jobIdFromSearch", () => {
    expect(jobIdFromSearch(searchWithJob("?a=1", ID))).toBe(ID);
    expect(jobIdFromSearch(searchWithJob(searchWithJob("?a=1", ID), null))).toBeNull();
  });
});

describe("fileSha256", () => {
  it("returns the lowercase hex digest of the bytes", async () => {
    const hash = await fileSha256(new Blob(["abc"]), globalThis.crypto.subtle);
    expect(hash).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("uses the global subtle crypto when none is passed", async () => {
    expect(await fileSha256(new Blob(["abc"]))).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });

  it("zero pads bytes below 0x10 so the digest is always 64 characters", async () => {
    // the digest of "b" has a 00 byte, a missing pad would shorten it
    const hash = await fileSha256(new Blob(["b"]), globalThis.crypto.subtle);
    expect(hash).toBe("3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d");
    expect(hash).toHaveLength(64);
  });

  it("hex encodes whatever the injected subtle returns", async () => {
    const subtle = { digest: vi.fn(async () => new Uint8Array([0x01, 0xab, 0x00, 0xff]).buffer) };
    const hash = await fileSha256(new Blob(["abc"]), subtle as unknown as SubtleCrypto);
    expect(hash).toBe("01ab00ff");
    expect(subtle.digest).toHaveBeenCalledWith("SHA-256", expect.any(ArrayBuffer));
  });

  // an explicit undefined falls back to the default parameter, so the missing case
  // has to come from the global itself, the way it does on a lan address
  describe("without subtle crypto", () => {
    beforeEach(() => {
      vi.stubGlobal("crypto", {});
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("is null when undefined is passed", async () => {
      expect(await fileSha256(new Blob(["abc"]), undefined)).toBeNull();
    });

    it("is null when the argument is left out", async () => {
      expect(await fileSha256(new Blob(["abc"]))).toBeNull();
    });

    it("does not read the file", async () => {
      const file = new Blob(["abc"]);
      const read = vi.spyOn(file, "arrayBuffer");
      await fileSha256(file);
      expect(read).not.toHaveBeenCalled();
    });
  });
});

describe("formatJobDate", () => {
  // built from a local date so the expected text holds in any timezone
  it("formats local time as YYYY-MM-DD HH:MM", () => {
    const local = new Date(2026, 2, 2, 10, 15, 30);
    expect(formatJobDate(local.toISOString())).toBe("2026-03-02 10:15");
  });

  it("zero pads month, day, hour and minute", () => {
    const local = new Date(2026, 0, 5, 3, 7);
    expect(formatJobDate(local.toISOString())).toBe("2026-01-05 03:07");
  });

  it("uses a 24 hour clock", () => {
    const local = new Date(2026, 10, 30, 23, 59, 59);
    expect(formatJobDate(local.toISOString())).toBe("2026-11-30 23:59");
    const midnight = new Date(2026, 5, 1, 0, 0);
    expect(formatJobDate(midnight.toISOString())).toBe("2026-06-01 00:00");
  });

  it("reads the offset form the backend writes", () => {
    const instant = new Date("2026-03-02T10:15:30.250+00:00");
    const expected = [
      instant.getFullYear(),
      String(instant.getMonth() + 1).padStart(2, "0"),
      String(instant.getDate()).padStart(2, "0"),
    ].join("-");
    const time = `${String(instant.getHours()).padStart(2, "0")}:${String(instant.getMinutes()).padStart(2, "0")}`;
    expect(formatJobDate("2026-03-02T10:15:30.250+00:00")).toBe(`${expected} ${time}`);
  });

  it("returns the input unchanged when it doesn't parse", () => {
    expect(formatJobDate("not a date")).toBe("not a date");
    expect(formatJobDate("")).toBe("");
  });
});

describe("formatEditCount", () => {
  it("says no edits for zero", () => {
    expect(formatEditCount(0)).toBe("no edits");
  });

  it("uses the singular for one", () => {
    expect(formatEditCount(1)).toBe("1 edit");
  });

  it("uses the plural from two up", () => {
    expect(formatEditCount(2)).toBe("2 edits");
    expect(formatEditCount(12)).toBe("12 edits");
  });
});

describe("groupJobs", () => {
  const A = "a".repeat(64);
  const B = "b".repeat(64);
  const ids = (jobs: JobSummary[]) => jobs.map((entry) => entry.job_id);
  // job ids only, so a case reads as the order it expects
  const shape = (jobs: JobSummary[]) =>
    groupJobs(jobs).map((group) => ({ sha256: group.sha256, latest: group.latest.job_id, older: ids(group.older) }));

  it("is empty for an empty list", () => {
    expect(groupJobs([])).toEqual([]);
  });

  it("leaves a single job alone, with nothing older", () => {
    const only = job("j1", A);
    expect(groupJobs([only])).toEqual([{ sha256: A, latest: only, older: [] }]);
  });

  it("groups three jobs of one file and one of another, interleaved", () => {
    expect(shape([job("j1", A), job("j2", B), job("j3", A), job("j4", A)])).toEqual([
      { sha256: A, latest: "j1", older: ["j3", "j4"] },
      { sha256: B, latest: "j2", older: [] },
    ]);
  });

  it("puts a group where its newest job is", () => {
    // b is newest, a only follows even though it has more jobs
    expect(shape([job("j1", B), job("j2", A), job("j3", A), job("j4", A)])).toEqual([
      { sha256: B, latest: "j1", older: [] },
      { sha256: A, latest: "j2", older: ["j3", "j4"] },
    ]);
  });

  it("keeps the server's order inside a group", () => {
    // the ids aren't sorted, so a sort by id would show
    expect(shape([job("j3", A), job("j1", A), job("j2", A)])).toEqual([
      { sha256: A, latest: "j3", older: ["j1", "j2"] },
    ]);
  });

  it("leaves demo jobs out, also when they share a hash with a song", () => {
    const jobs = [job("j1", B, { demo: true }), job("j2", A), job("j3", A, { demo: true }), job("j4", A)];
    expect(shape(jobs)).toEqual([{ sha256: A, latest: "j2", older: ["j4"] }]);
  });

  it("is empty when every job is a demo", () => {
    expect(groupJobs([job("j1", A, { demo: true }), job("j2", B, { demo: true })])).toEqual([]);
  });

  it("returns the job objects themselves and doesn't touch the input", () => {
    const first = job("j1", A);
    const second = job("j2", A);
    const input = [first, second];
    const [group] = groupJobs(input);
    expect(group?.latest).toBe(first);
    expect(group?.older[0]).toBe(second);
    expect(input).toEqual([first, second]);
  });
});
