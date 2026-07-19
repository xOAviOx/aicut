import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { api } from "../api";
import { clock } from "../lib/clock";
import { player } from "../lib/player";
import { fmtClock } from "../lib/format";

// Draw the peak envelope as centered, mirrored vertical bars on a canvas that
// fills the timeline bar. Cheap and imperative — no React re-render per frame.
function drawWaveform(canvas: HTMLCanvasElement, peaks: number[]) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth;
  const cssH = canvas.clientHeight;
  if (cssW === 0 || cssH === 0) return;
  canvas.width = Math.max(1, Math.floor(cssW * dpr));
  canvas.height = Math.max(1, Math.floor(cssH * dpr));
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if (peaks.length === 0) return;

  const mid = cssH / 2;
  const barW = cssW / peaks.length;
  ctx.fillStyle = "rgba(214, 199, 168, 0.28)"; // parchment, quiet
  for (let i = 0; i < peaks.length; i++) {
    const h = Math.max(0.5, peaks[i] * (cssH - 3));
    const x = i * barW;
    const w = Math.max(0.5, barW - 0.35);
    ctx.fillRect(x, mid - h / 2, w, h);
  }
}

export default function Timeline() {
  const duration = useStore((s) => s.duration());
  const keep = useStore((s) => s.keepRanges());
  const projectId = useStore((s) => s.project?.id);
  const barRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; t: number } | null>(null);
  const [peaks, setPeaks] = useState<number[]>([]);

  // playhead position, driven imperatively by the clock (no re-render).
  useEffect(() => {
    return clock.subscribe((t) => {
      if (playheadRef.current && duration > 0) {
        playheadRef.current.style.left = `${(t / duration) * 100}%`;
      }
    });
  }, [duration]);

  // fetch the waveform peaks once per project (backend caches them on disk).
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api
      .waveform(projectId)
      .then((r) => {
        if (!cancelled) setPeaks(r.peaks ?? []);
      })
      .catch(() => {
        /* waveform is a nicety; ignore failures */
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // (re)draw on peaks change and whenever the bar resizes.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const redraw = () => drawWaveform(canvas, peaks);
    redraw();
    const ro = new ResizeObserver(redraw);
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [peaks]);

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
        className="relative h-12 cursor-pointer overflow-hidden rounded-md border border-ink-700"
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
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />
        {keptPct.map((k, i) => (
          <div
            key={i}
            className="absolute top-0 h-full bg-accent/20"
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
