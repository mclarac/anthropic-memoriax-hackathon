import { describe, expect, it } from "vitest";
import { diffLines } from "./line-diff";

describe("diffLines", () => {
  it("marks every line as added when there was no before", () => {
    expect(diffLines(null, "a\nb")).toEqual([
      { kind: "add", text: "a" },
      { kind: "add", text: "b" },
    ]);
  });

  it("marks every line as removed when there is no after", () => {
    expect(diffLines("a\nb", null)).toEqual([
      { kind: "remove", text: "a" },
      { kind: "remove", text: "b" },
    ]);
  });

  it("keeps unchanged lines as context", () => {
    expect(diffLines("a\nb", "a\nb")).toEqual([
      { kind: "same", text: "a" },
      { kind: "same", text: "b" },
    ]);
  });

  it("shows a changed line as a removal followed by an addition", () => {
    expect(diffLines("a\nold\nc", "a\nnew\nc")).toEqual([
      { kind: "same", text: "a" },
      { kind: "remove", text: "old" },
      { kind: "add", text: "new" },
      { kind: "same", text: "c" },
    ]);
  });

  it("detects an insertion in the middle", () => {
    expect(diffLines("a\nc", "a\nb\nc")).toEqual([
      { kind: "same", text: "a" },
      { kind: "add", text: "b" },
      { kind: "same", text: "c" },
    ]);
  });

  it("returns nothing for two empty sides", () => {
    expect(diffLines(null, null)).toEqual([]);
    expect(diffLines("", "")).toEqual([]);
  });

  it("ignores a single trailing newline so files do not show a phantom blank line", () => {
    expect(diffLines("a\n", "a\n")).toEqual([{ kind: "same", text: "a" }]);
  });
});
