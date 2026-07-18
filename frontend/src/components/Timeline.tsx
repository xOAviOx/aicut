import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { clock } from "../lib/clock";
import { player } from "../lib/player";
import { fmtClock } from "../lib/format";

export default function Timeline() {
  const duration = useStore((s) => s.duration());
  const keep = useStore((s) => s.keepRanges());
  const barRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; t: number } | null>(null);

  // playhead position, driven imperatively by the clock (no re-render).
  useEffect(() => {
    return clock.subscribe((t) => {
      if (playheadRef.current && duration > 0) {
        playheadRef.current.style.left = `${(t / duration) * 100}%`;
      }
    });
  }, [duration]);

  const keptPct = useMemo(
    () =>
      duration > 0
        ? keep.map(([s, e]) => ({ left: (s / duration) * 100, width: ((e - s) / duration) * 100 }))
        : [],
    [keep, duration],
  );

  const seekFromEvent = (clientX: number) => {
    const el = barRef.current;
    if (!el || duration <= 0) return;
    const rect = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    player.seek(frac * duration);
  };

  return (
    <div className="select-none">
      <div
        ref={barRef}
        onClick={(e) => seekFromEvent(e.clientX)}
        onMouseMove={(e) => {
          const rect = barRef.current!.getBoundingClientRect();
          const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
          setHover({ x: e.clientX - rect.left, t: frac * duration });
        }}
        onMouseLeave={() => setHover(null)}
        className="relative h-9 cursor-pointer overflow-hidden rounded-md border border-ink-700"
        style={{
          // cut regions: hatched, dimmed
          backgroundImage:
            "repeating-linear-gradient(45deg, rgba(120,110,90,0.10) 0 6px, rgba(120,110,90,0.03) 6px 12px)",
          backgroundColor: "#1c1a13",
        }}
        role="slider"
        aria-label="timeline"
        aria-valuemin={0}
        aria-valuemax={duration}
      >
        {keptPct.map((k, i) => (
          <div
            key={i}
            className="absolute top-0 h-full bg-accent/25"
            style={{ left: `${k.left}%`, width: `${k.width}%` }}
          />
        ))}
        <div
          ref={playheadRef}
          className="pointer-events-none absolute top-0 h-full w-[2px] bg-accent shadow-[0_0_6px_rgba(217,164,65,0.6)]"
          style={{ left: 0 }}
        />
        {hover && (
          <div
            className="tc pointer-events-none absolute -top-6 z-10 -translate-x-1/2 rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-parchment-100"
            style={{ left: hover.x }}
          >
            {fmtClock(hover.t)}
          </div>
        )}
      </div>
    </div>
  );
}
