import { describe, expect, it } from "vitest";
import {
  coordsToWordRefs,
  rangeBetween,
  type FlatWord,
  type WordCoord,
} from "../lib/transcriptSelection";

describe("coordsToWordRefs", () => {
  it("collapses contiguous words into one ref", () => {
    const coords: WordCoord[] = [
      { segmentId: 1, wordIndex: 2 },
      { segmentId: 1, wordIndex: 3 },
      { segmentId: 1, wordIndex: 4 },
    ];
    expect(coordsToWordRefs(coords)).toEqual([
      { segment_id: 1, word_index_start: 2, word_index_end: 4 },
    ]);
  });

  it("splits non-contiguous words and separates segments", () => {
    const coords: WordCoord[] = [
      { segmentId: 1, wordIndex: 0 },
      { segmentId: 1, wordIndex: 1 },
      { segmentId: 1, wordIndex: 5 },
      { segmentId: 2, wordIndex: 0 },
    ];
    const refs = coordsToWordRefs(coords);
    expect(refs).toContainEqual({ segment_id: 1, word_index_start: 0, word_index_end: 1 });
    expect(refs).toContainEqual({ segment_id: 1, word_index_start: 5, word_index_end: 5 });
    expect(refs).toContainEqual({ segment_id: 2, word_index_start: 0, word_index_end: 0 });
    expect(refs).toHaveLength(3);
  });

  it("dedupes and handles empty", () => {
    expect(coordsToWordRefs([])).toEqual([]);
    const dup: WordCoord[] = [
      { segmentId: 1, wordIndex: 1 },
      { segmentId: 1, wordIndex: 1 },
    ];
    expect(coordsToWordRefs(dup)).toEqual([
      { segment_id: 1, word_index_start: 1, word_index_end: 1 },
    ]);
  });
});

describe("rangeBetween", () => {
  const flat: FlatWord[] = [
    { segmentId: 1, wordIndex: 0, globalIndex: 0 },
    { segmentId: 1, wordIndex: 1, globalIndex: 1 },
    { segmentId: 2, wordIndex: 0, globalIndex: 2 },
    { segmentId: 2, wordIndex: 1, globalIndex: 3 },
  ];
  it("selects inclusive range regardless of direction", () => {
    expect(rangeBetween(flat, 3, 1)).toEqual([
      { segmentId: 1, wordIndex: 1 },
      { segmentId: 2, wordIndex: 0 },
      { segmentId: 2, wordIndex: 1 },
    ]);
  });
});
