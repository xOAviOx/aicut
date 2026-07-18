import { describe, expect, it } from "vitest";
import {
  contains,
  inverseRemap,
  isSpanCut,
  nextKeepStart,
  normalize,
  remapTime,
  total,
} from "../lib/rangemath";
import type { Span } from "../types";

describe("normalize", () => {
  it("merges overlapping and adjacent spans", () => {
    expect(normalize([[0, 1], [1, 2]])).toEqual([[0, 2]]);
    expect(normalize([[0, 2], [1, 3]])).toEqual([[0, 3]]);
  });
  it("drops zero/negative spans and sorts", () => {
    expect(normalize([[5, 5], [3, 4], [1, 2]])).toEqual([[1, 2], [3, 4]]);
  });
});

describe("remapTime / inverseRemap", () => {
  const keep: Span[] = [
    [0, 10],
    [20, 30],
  ];
  it("maps source to output through the gap", () => {
    expect(remapTime(5, keep)).toBe(5);
    expect(remapTime(15, keep)).toBe(10); // inside cut -> boundary
    expect(remapTime(25, keep)).toBe(15);
    expect(remapTime(100, keep)).toBe(20); // after all keeps -> total
  });
  it("inverse is a left inverse on kept times", () => {
    // interior points only — times exactly on a cut/keep boundary are ambiguous
    for (const t of [0, 3, 9.5, 20.1, 25, 29.9]) {
      expect(inverseRemap(remapTime(t, keep), keep)).toBeCloseTo(t, 6);
    }
  });
  it("total equals output duration", () => {
    expect(total(keep)).toBe(20);
  });
});

describe("preview helpers", () => {
  const keep: Span[] = [
    [0, 10],
    [20, 30],
  ];
  it("contains checks kept spans", () => {
    expect(contains(keep, 5)).toBe(true);
    expect(contains(keep, 15)).toBe(false);
  });
  it("nextKeepStart finds the skip target", () => {
    expect(nextKeepStart(keep, 12)).toBe(20);
    expect(nextKeepStart(keep, 25)).toBe(null);
  });
  it("isSpanCut uses the midpoint", () => {
    expect(isSpanCut(keep, 14, 16)).toBe(true); // mid 15 in gap
    expect(isSpanCut(keep, 4, 6)).toBe(false);
  });
});
