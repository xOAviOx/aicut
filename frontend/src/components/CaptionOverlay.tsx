import { useEffect, useRef } from "react";
import { useStore, headEdl } from "../store";
import { clock } from "../lib/clock";
import type { Segment } from "../types";

// DOM overlay preview of burned-in captions (no ASS in preview, spec §6.3).
// Driven imperatively by the clock so it never re-renders the tree.
export default function CaptionOverlay() {
  const project = useStore((s) => s.project);
  const transcript = useStore((s) => s.transcript);
  const previewMode = useStore((s) => s.previewMode);
  const edl = headEdl(project);
  const enabled = previewMode === "edited" && !!edl?.captions.enabled;
  const granularity = edl?.captions.granularity ?? "segment";
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled || !transcript) {
      if (ref.current) ref.current.textContent = "";
      return;
    }
    const segs = transcript.segments;
    const findSeg = (t: number): Segment | null => {
      let lo = 0;
      let hi = segs.length - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (t < segs[mid].start) hi = mid - 1;
        else if (t >= segs[mid].end) lo = mid + 1;
        else return segs[mid];
      }
      return null;
    };
    return clock.subscribe((t) => {
      if (!ref.current) return;
      const seg = findSeg(t);
      let text = "";
      if (seg) {
        if (granularity === "word") {
          const w = seg.words.find((w) => t >= w.start && t < w.end);
          text = w?.w ?? "";
        } else {
          text = seg.text;
        }
      }
      ref.current.textContent = text;
    });
  }, [enabled, transcript, granularity]);

  if (!enabled) return null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-[6%] flex justify-center px-4">
      <div
        ref={ref}
        className="max-w-[92%] text-balance text-center font-ui font-semibold leading-tight text-white"
        style={{
          textShadow: "0 0 4px rgba(0,0,0,0.9), 0 2px 3px rgba(0,0,0,0.9)",
          fontSize: "clamp(13px, 2.6vw, 22px)",
        }}
      />
    </div>
  );
}
