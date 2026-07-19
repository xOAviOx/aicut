import { memo, useEffect, useMemo, useRef } from "react";
import { useStore } from "../store";
import { clock } from "../lib/clock";
import { player } from "../lib/player";
import { isSpanCut } from "../lib/rangemath";
import { fmtClock } from "../lib/format";
import type { Segment, Span } from "../types";
import type { WordCoord } from "../lib/transcriptSelection";

interface FlatWord {
  globalIndex: number;
  segId: number;
  wordIdx: number;
  start: number;
  end: number;
}

// Map whisper's per-word probability to a shading class (styled only when the
// transcript container carries `.show-confidence`).
function confClass(prob: number | null | undefined): string {
  if (prob == null) return "";
  if (prob < 0.5) return "word-lowconf";
  if (prob < 0.72) return "word-midconf";
  return "";
}

const SegmentRow = memo(function SegmentRow({
  seg,
  baseIndex,
  keep,
  showCutText,
  registerEl,
}: {
  seg: Segment;
  baseIndex: number;
  keep: Span[];
  showCutText: boolean;
  registerEl: (gi: number, el: HTMLElement | null) => void;
}) {
  return (
    <p className="mb-3 leading-relaxed" data-seg={seg.id}>
      <span className="tc mr-3 select-none align-baseline text-[11px] text-parchment-600">
        {fmtClock(seg.start)}
      </span>
      {seg.words.map((w, i) => {
        const gi = baseIndex + i;
        const cut = isSpanCut(keep, w.start, w.end);
        if (cut && !showCutText) return null;
        return (
          <span
            key={i}
            ref={(el) => registerEl(gi, el)}
            data-gi={gi}
            className={`cursor-text select-none rounded-[3px] px-[1px] ${cut ? "word-cut" : ""} ${confClass(w.prob)}`}
          >
            {w.w}{" "}
          </span>
        );
      })}
    </p>
  );
});

export default function Transcript() {
  const transcript = useStore((s) => s.transcript);
  const keep = useStore((s) => s.keepRanges());
  const showCutText = useStore((s) => s.showCutText);
  const showConfidence = useStore((s) => s.showConfidence);
  const follow = useStore((s) => s.follow);
  const toggleFollow = useStore((s) => s.toggleFollow);
  const toggleShowCutText = useStore((s) => s.toggleShowCutText);
  const toggleShowConfidence = useStore((s) => s.toggleShowConfidence);
  const setSelection = useStore((s) => s.setSelection);

  const scrollRef = useRef<HTMLDivElement>(null);
  const wordEls = useRef<(HTMLElement | null)[]>([]);
  const activeIdx = useRef<number>(-1);

  const flat: FlatWord[] = useMemo(() => {
    const out: FlatWord[] = [];
    if (!transcript) return out;
    let gi = 0;
    for (const seg of transcript.segments) {
      for (let i = 0; i < seg.words.length; i++) {
        out.push({
          globalIndex: gi,
          segId: seg.id,
          wordIdx: i,
          start: seg.words[i].start,
          end: seg.words[i].end,
        });
        gi++;
      }
    }
    return out;
  }, [transcript]);

  const baseIndices = useMemo(() => {
    const bases: number[] = [];
    let gi = 0;
    for (const seg of transcript?.segments ?? []) {
      bases.push(gi);
      gi += seg.words.length;
    }
    return bases;
  }, [transcript]);

  const registerEl = (gi: number, el: HTMLElement | null) => {
    wordEls.current[gi] = el;
  };

  // ---- imperative active-word highlight (clock-driven, no re-render) ----
  useEffect(() => {
    let lastScroll = 0;
    const findActive = (t: number): number => {
      let lo = 0;
      let hi = flat.length - 1;
      let ans = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (t < flat[mid].start) hi = mid - 1;
        else if (t >= flat[mid].end) lo = mid + 1;
        else {
          ans = mid;
          break;
        }
      }
      return ans;
    };
    return clock.subscribe((t) => {
      const idx = findActive(t);
      if (idx === activeIdx.current) return;
      wordEls.current[activeIdx.current]?.classList.remove("word-active");
      const el = wordEls.current[idx];
      if (el) {
        el.classList.add("word-active");
        if (follow && Date.now() - lastScroll > 250) {
          lastScroll = Date.now();
          el.scrollIntoView({ block: "center", behavior: "smooth" });
        }
      }
      activeIdx.current = idx;
    });
  }, [flat, follow]);

  // ---- selection (drag / shift-click), imperative class toggling ----
  const selGis = useRef<Set<number>>(new Set());
  const anchorGi = useRef<number | null>(null);
  const dragging = useRef(false);

  useEffect(() => {
    const paint = (next: Set<number>) => {
      for (const gi of selGis.current) {
        if (!next.has(gi)) wordEls.current[gi]?.classList.remove("word-selected");
      }
      for (const gi of next) wordEls.current[gi]?.classList.add("word-selected");
      selGis.current = next;
    };
    const rangeSet = (a: number, b: number): Set<number> => {
      const lo = Math.min(a, b);
      const hi = Math.max(a, b);
      const s = new Set<number>();
      for (let i = lo; i <= hi; i++) s.add(i);
      return s;
    };
    const commit = () => {
      const coords: WordCoord[] = [];
      for (const gi of selGis.current) {
        const f = flat[gi];
        if (f) coords.push({ segmentId: f.segId, wordIndex: f.wordIdx });
      }
      setSelection(coords, anchorGi.current);
    };
    const giFromEvent = (e: Event): number | null => {
      const el = (e.target as HTMLElement)?.closest?.("[data-gi]") as HTMLElement | null;
      if (!el) return null;
      const gi = Number(el.dataset.gi);
      return Number.isNaN(gi) ? null : gi;
    };

    const onDown = (e: MouseEvent) => {
      const gi = giFromEvent(e);
      if (gi === null) {
        // clicked empty transcript area → clear selection
        paint(new Set());
        anchorGi.current = null;
        commit();
        return;
      }
      e.preventDefault();
      const f = flat[gi];
      if (e.shiftKey && anchorGi.current !== null) {
        paint(rangeSet(anchorGi.current, gi));
      } else {
        anchorGi.current = gi;
        paint(new Set([gi]));
        if (f) player.seek(f.start);
      }
      dragging.current = true;
    };
    const onMove = (e: MouseEvent) => {
      if (!dragging.current || anchorGi.current === null) return;
      const gi = giFromEvent(e);
      if (gi === null) return;
      paint(rangeSet(anchorGi.current, gi));
    };
    const onUp = () => {
      if (dragging.current) {
        dragging.current = false;
        commit();
      }
    };

    const node = scrollRef.current;
    node?.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      node?.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [flat, setSelection]);

  // Clearing selection from elsewhere (undo, cut) should wipe painted classes.
  const selectionLen = useStore((s) => s.selection.length);
  useEffect(() => {
    if (selectionLen === 0 && selGis.current.size > 0) {
      for (const gi of selGis.current) wordEls.current[gi]?.classList.remove("word-selected");
      selGis.current = new Set();
      anchorGi.current = null;
    }
  }, [selectionLen]);

  // disable follow when the user scrolls manually (wheel / touch drag)
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const onManualScroll = () => {
      if (useStore.getState().follow) useStore.getState().toggleFollow();
    };
    node.addEventListener("wheel", onManualScroll, { passive: true });
    node.addEventListener("touchmove", onManualScroll, { passive: true });
    return () => {
      node.removeEventListener("wheel", onManualScroll);
      node.removeEventListener("touchmove", onManualScroll);
    };
  }, []);

  if (!transcript) return null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-ink-700/50 px-5 py-2">
        <span className="font-ui text-xs uppercase tracking-widest text-parchment-600">
          Transcript
        </span>
        <div className="flex items-center gap-4">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-parchment-400">
            <input
              type="checkbox"
              checked={showCutText}
              onChange={toggleShowCutText}
              className="accent-accent"
            />
            show cut
          </label>
          <label
            className="flex cursor-pointer items-center gap-1.5 text-xs text-parchment-400"
            title="Underline words whisper was unsure about (possible mishearings)"
          >
            <input
              type="checkbox"
              checked={showConfidence}
              onChange={toggleShowConfidence}
              className="accent-accent"
            />
            confidence
          </label>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-parchment-400">
            <input type="checkbox" checked={follow} onChange={toggleFollow} className="accent-accent" />
            follow
          </label>
        </div>
      </div>
      <div
        ref={scrollRef}
        className={`flex-1 overflow-y-auto px-6 py-5 font-reading text-transcript text-parchment-100 ${showConfidence ? "show-confidence" : ""}`}
      >
        {transcript.segments.map((seg, si) => (
          <SegmentRow
            key={seg.id}
            seg={seg}
            baseIndex={baseIndices[si]}
            keep={keep}
            showCutText={showCutText}
            registerEl={registerEl}
          />
        ))}
      </div>
      <SelectionBar />
    </div>
  );
}

// A slim action bar that appears when words are selected.
function SelectionBar() {
  const selection = useStore((s) => s.selection);
  const transcript = useStore((s) => s.transcript);
  const keep = useStore((s) => s.keepRanges());
  const cutSelection = useStore((s) => s.cutSelection);
  const restoreSelection = useStore((s) => s.restoreSelection);
  const busy = useStore((s) => s.busy);
  if (selection.length === 0 || !transcript) return null;

  // does the selection contain any kept / cut words?
  let hasKept = false;
  let hasCut = false;
  const segMap = new Map(transcript.segments.map((s) => [s.id, s]));
  for (const c of selection) {
    const seg = segMap.get(c.segmentId);
    const w = seg?.words[c.wordIndex];
    if (!w) continue;
    if (isSpanCut(keep, w.start, w.end)) hasCut = true;
    else hasKept = true;
  }

  return (
    <div className="flex items-center justify-between border-t border-ink-700/60 bg-ink-850 px-5 py-2">
      <span className="text-xs text-parchment-400">
        {selection.length} word{selection.length !== 1 ? "s" : ""} selected
      </span>
      <div className="flex items-center gap-2">
        {hasKept && (
          <button
            onClick={cutSelection}
            disabled={busy}
            className="rounded-md bg-redact/90 px-3 py-1 text-xs font-medium text-parchment-100 transition hover:bg-redact disabled:opacity-50"
          >
            Delete
          </button>
        )}
        {hasCut && (
          <button
            onClick={restoreSelection}
            disabled={busy}
            className="rounded-md border border-ink-600 px-3 py-1 text-xs text-parchment-200 transition hover:border-accent disabled:opacity-50"
          >
            Restore
          </button>
        )}
      </div>
    </div>
  );
}
