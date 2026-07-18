// Map a set of selected words (each identified by segment id + word index)
// into compact contiguous WordRef ranges — what a transcript deletion compiles
// to on the backend (cut_words). Pure + unit-tested (src/test/selection.test.ts).

import type { WordRef } from "../types";

export interface WordCoord {
  segmentId: number;
  wordIndex: number;
}

// Group selected coords into contiguous [start,end] runs within each segment.
export function coordsToWordRefs(coords: WordCoord[]): WordRef[] {
  if (coords.length === 0) return [];
  const bySeg = new Map<number, number[]>();
  for (const c of coords) {
    const arr = bySeg.get(c.segmentId) ?? [];
    arr.push(c.wordIndex);
    bySeg.set(c.segmentId, arr);
  }
  const refs: WordRef[] = [];
  for (const [segmentId, indicesRaw] of bySeg) {
    const indices = [...new Set(indicesRaw)].sort((a, b) => a - b);
    let runStart = indices[0];
    let prev = indices[0];
    for (let i = 1; i < indices.length; i++) {
      const idx = indices[i];
      if (idx === prev + 1) {
        prev = idx;
      } else {
        refs.push({ segment_id: segmentId, word_index_start: runStart, word_index_end: prev });
        runStart = idx;
        prev = idx;
      }
    }
    refs.push({ segment_id: segmentId, word_index_start: runStart, word_index_end: prev });
  }
  return refs;
}

// Build the ordered list of word coords between an anchor and focus (inclusive),
// given the flat document order of words. Used for shift-click / drag selection.
export interface FlatWord {
  segmentId: number;
  wordIndex: number;
  globalIndex: number;
}

export function rangeBetween(
  flat: FlatWord[],
  anchorGlobal: number,
  focusGlobal: number,
): WordCoord[] {
  const lo = Math.min(anchorGlobal, focusGlobal);
  const hi = Math.max(anchorGlobal, focusGlobal);
  return flat
    .filter((f) => f.globalIndex >= lo && f.globalIndex <= hi)
    .map((f) => ({ segmentId: f.segmentId, wordIndex: f.wordIndex }));
}
