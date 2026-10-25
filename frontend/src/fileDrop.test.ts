import { describe, expect, it } from "vitest";
import { carriesFiles, isAudioName } from "./fileDrop";

describe("isAudioName", () => {
  it("takes the extensions the server takes, in any case", () => {
    for (const name of ["a.mp3", "b.WAV", "c.flac", "d.ogg", "e.m4a", "a song - title.mp3"]) expect(isAudioName(name)).toBe(true);
  });

  it("turns down anything else", () => {
    for (const name of ["notes.txt", "song.mp3.zip", "mp3", "cover.png"]) expect(isAudioName(name)).toBe(false);
  });
});

describe("carriesFiles", () => {
  it("lights up for files only", () => {
    expect(carriesFiles(["Files"])).toBe(true);
    expect(carriesFiles(["text/plain", "Files"])).toBe(true);
    expect(carriesFiles(["text/uri-list"])).toBe(false);
    expect(carriesFiles(null)).toBe(false);
  });
});
