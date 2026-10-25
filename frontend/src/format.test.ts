import { describe, expect, it } from "vitest";
import { elapsedText, failureText, reanalysisFailureText } from "./format";
import type { JobError } from "./types/api";

const FFMPEG_MISSING: JobError = { stage: "decode", message: "ffmpeg not found on PATH" };

describe("reanalysisFailureText", () => {
  it("names the stage and says the last good report is on screen", () => {
    const error: JobError = { stage: "beats", message: "found 2 beats between the trim points, need at least 4" };
    expect(reanalysisFailureText(error)).toBe(
      "re-analysis failed at beats — found 2 beats between the trim points, need at least 4. showing the last good report",
    );
  });

  it("turns the missing binary messages into the same hints as failureText", () => {
    expect(reanalysisFailureText(FFMPEG_MISSING)).toBe(
      "re-analysis failed at decode — check that ffmpeg is on PATH. showing the last good report",
    );
    expect(reanalysisFailureText({ stage: "decode", message: "ffprobe not found on PATH" })).toBe(
      "re-analysis failed at decode — check that ffprobe is on PATH. showing the last good report",
    );
  });

  it("keeps a message it has no hint for as it is", () => {
    const error: JobError = { stage: "queued", message: "server restarted before the job finished" };
    expect(reanalysisFailureText(error)).toBe(
      "re-analysis failed at queued — server restarted before the job finished. showing the last good report",
    );
  });
});

describe("failureText", () => {
  it("still reads as a failed first analysis", () => {
    expect(failureText(FFMPEG_MISSING)).toBe("analysis failed at decode — check that ffmpeg is on PATH");
    expect(failureText({ stage: "trim", message: "audio is silent" })).toBe("analysis failed at trim — audio is silent");
  });
});

describe("elapsedText", () => {
  it("counts minutes and seconds, and hours past one", () => {
    expect(elapsedText(0)).toBe("0:00");
    expect(elapsedText(7999)).toBe("0:07");
    expect(elapsedText(83_000)).toBe("1:23");
    expect(elapsedText(3_723_000)).toBe("1:02:03");
    // a clock that moved back doesn't show a minus
    expect(elapsedText(-500)).toBe("0:00");
  });
});
