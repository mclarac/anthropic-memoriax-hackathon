import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, linesToList, slotStatusLabel } from "./format";

describe("formatBytes", () => {
  it.each([
    [0, "0 B"],
    [512, "512 B"],
    [2048, "2.0 KB"],
    [1536000, "1.5 MB"],
  ])("formats %d", (bytes, expected) => {
    expect(formatBytes(bytes)).toBe(expected);
  });
});

describe("formatDuration", () => {
  it("shows a dash while unknown", () => {
    expect(formatDuration(null)).toBe("-");
  });
  it("uses milliseconds under a second", () => {
    expect(formatDuration(480)).toBe("480 ms");
  });
  it("uses seconds with one decimal under a minute", () => {
    expect(formatDuration(1240)).toBe("1.2 s");
  });
  it("uses minutes and seconds beyond a minute", () => {
    expect(formatDuration(125000)).toBe("2 min 5 s");
  });
});

describe("linesToList", () => {
  it("splits on lines, trims and drops blanks", () => {
    expect(linesToList("  a \n\n b\r\n")).toEqual(["a", "b"]);
  });
});

describe("slotStatusLabel", () => {
  it("calls rep_unsure unsure", () => {
    expect(slotStatusLabel("rep_unsure")).toBe("unsure");
    expect(slotStatusLabel("confirmed")).toBe("confirmed");
  });
});
