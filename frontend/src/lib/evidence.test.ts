import { describe, expect, it } from "vitest";
import { evidenceParts } from "./evidence";

describe("stored page offsets", () => {
  it("preserves Python code point references after non-BMP characters", () => {
    expect(evidenceParts("A🧪متن🧬Z", 2, 5)).toEqual({ before: "A🧪", quote: "متن", after: "🧬Z" });
  });
  it("rejects out-of-page and empty references", () => {
    for (const [start, end] of [[-1, 2], [0, 9], [1, 1], [0.5, 2]]) expect(evidenceParts("test", start, end)).toBeNull();
  });
});
