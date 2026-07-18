// Frontend mirror of backend/aicut/rangemath.py — the subset the UI needs for
// skip-preview, the timeline strip, seeking, and caption timing. Unit-tested
// against the same cases as the Python side (src/test/rangemath.test.ts).

import type { Span } from "../types";

export const EPS = 1e-6;
export const MIN_KEEP = 0.25;

export function normalize(ranges: Span[], eps = EPS): Span[] {
  const cleaned = ranges
    .map(([s, e]) => [Number(s), Number(e)] as Span)
    .filter(([s, e]) => e - s > eps)
    .sort((a, b) => a[0] - b[0]);
  if (cleaned.length === 0) return [];
  const out: Span[] = [cleaned[0]];
  for (let i = 1; i < cleaned.length; i++) {
    const [s, e] = cleaned[i];
    const last = out[out.length - 1];
    if (s <= last[1] + eps) {
      last[1] = Math.max(last[1], e);
    } else {
      out.push([s, e]);
    }
  }
  return out;
}

export function total(ranges: Span[]): number {
  return normalize(ranges).reduce((acc, [s, e]) => acc + (e - s), 0);
}

// source time -> output time
export function remapTime(t: number, keep: Span[]): number {
  const k = normalize(keep);
  let out = 0;
  for (const [s, e] of k) {
    if (t < s) return out;
    if (t <= e) return out + (t - s);
    out += e - s;
  }
  return out;
}

// output time -> source time
export function inverseRemap(tOut: number, keep: Span[]): number {
  const k = normalize(keep);
  if (k.length === 0) return 0;
  if (tOut <= 0) return k[0][0];
  let acc = 0;
  for (const [s, e] of k) {
    const len = e - s;
    if (tOut <= acc + len + EPS) return s + (tOut - acc);
    acc += len;
  }
  return k[k.length - 1][1];
}

export function contains(keep: Span[], t: number): boolean {
  for (const [s, e] of normalize(keep)) {
    if (s - EPS <= t && t <= e + EPS) return true;
  }
  return false;
}

// First kept-span start strictly after t — where skip-preview jumps to.
export function nextKeepStart(keep: Span[], t: number): number | null {
  for (const [s] of normalize(keep)) {
    if (s > t + EPS) return s;
  }
  return null;
}

// Is a word (by its time span midpoint) currently cut?
export function isSpanCut(keep: Span[], start: number, end: number): boolean {
  const mid = (start + end) / 2;
  return !contains(keep, mid);
}
