import { describe, expect, it, vi } from "vitest";
import { failureText } from "./format";
import { pollJob } from "./poll";
import type { JobStage, JobStatus } from "./types/api";

const queued: JobStatus = { status: "queued", stage: "queued", error: null };
const done: JobStatus = { status: "done", stage: "done", error: null };

function running(stage: JobStage): JobStatus {
  return { status: "running", stage, error: null };
}

// hands out the scripted statuses one per call, fetching past the end is a test bug
function scripted(steps: JobStatus[]) {
  let next = 0;
  return vi.fn(async (): Promise<JobStatus> => {
    const step = steps[next];
    if (step === undefined) throw new Error("fetched past the end of the script");
    next += 1;
    return step;
  });
}

function fakeSleep() {
  return vi.fn(async (_ms: number, _signal?: AbortSignal): Promise<void> => {});
}

describe("pollJob", () => {
  it("reports each stage change once and stops at done", async () => {
    const fetchStatus = scripted([
      queued,
      running("decode"),
      running("decode"),
      running("trim"),
      running("tempo"),
      done,
    ]);
    const sleep = fakeSleep();
    const stages: JobStage[] = [];

    const result = await pollJob(fetchStatus, {
      sleep,
      onUpdate: (status) => stages.push(status.stage),
    });

    // second decode is a repeat, so it never reaches onUpdate
    expect(stages).toEqual(["queued", "decode", "trim", "tempo", "done"]);
    expect(result).toEqual(done);
    expect(fetchStatus).toHaveBeenCalledTimes(6);
    expect(sleep).toHaveBeenCalledTimes(5);
    expect(sleep.mock.calls.map(([ms]) => ms)).toEqual([1000, 1000, 1000, 1000, 1000]);
  });

  it("resolves with the failed status and never fetches after it", async () => {
    const failed: JobStatus = {
      status: "failed",
      stage: "failed",
      error: { stage: "decode", message: "ffmpeg not found on PATH" },
    };
    const fetchStatus = scripted([queued, running("decode"), failed]);
    const sleep = fakeSleep();
    const stages: JobStage[] = [];

    const result = await pollJob(fetchStatus, {
      sleep,
      onUpdate: (status) => stages.push(status.stage),
    });

    expect(result).toEqual(failed);
    expect(stages).toEqual(["queued", "decode", "failed"]);
    expect(fetchStatus).toHaveBeenCalledTimes(3);
    expect(sleep).toHaveBeenCalledTimes(2);

    if (result.error === null) throw new Error("failed status should carry an error");
    expect(failureText(result.error)).toBe(
      "analysis failed at decode — check that ffmpeg is on PATH",
    );
  });

  it("rejects with AbortError when aborted mid-poll and stops fetching", async () => {
    const controller = new AbortController();
    const fetchStatus = vi.fn(async (): Promise<JobStatus> => running("decode"));
    let sleeps = 0;
    const sleep = vi.fn(async (_ms: number, _signal?: AbortSignal): Promise<void> => {
      sleeps += 1;
      // abort lands during the second wait, a sleep that ignores the signal still has to stop the loop
      if (sleeps === 2) controller.abort();
    });

    await expect(pollJob(fetchStatus, { sleep, signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(fetchStatus).toHaveBeenCalledTimes(2);

    // one macrotask, enough for a stray loop to sneak in another fetch if it were still alive
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });

  it("stops the default sleep as soon as the signal aborts", async () => {
    const controller = new AbortController();
    const fetchStatus = vi.fn(async (): Promise<JobStatus> => {
      // a macrotask, so it fires after the default 1000 ms sleep has started and before it ends
      setTimeout(() => controller.abort(), 0);
      return running("trim");
    });

    await expect(pollJob(fetchStatus, { signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("rejects with whatever fetchStatus throws", async () => {
    const boom = new Error("backend offline");
    const fetchStatus = vi
      .fn<() => Promise<JobStatus>>()
      .mockResolvedValueOnce(queued)
      .mockRejectedValueOnce(boom);
    const sleep = fakeSleep();

    await expect(pollJob(fetchStatus, { sleep })).rejects.toBe(boom);
    expect(fetchStatus).toHaveBeenCalledTimes(2);
  });
});
