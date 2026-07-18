import { useEffect, useRef } from "react";
import { useStore, headEdl } from "../store";
import { clock } from "../lib/clock";
import { player } from "../lib/player";
import { fmtClock } from "../lib/format";
import { nextKeepStart, contains } from "../lib/rangemath";
import CaptionOverlay from "./CaptionOverlay";

function TimeReadout() {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(
    () =>
      clock.subscribe((t) => {
        if (ref.current) ref.current.textContent = fmtClock(t);
      }),
    [],
  );
  return <span ref={ref} className="tc text-xs text-parchment-200" />;
}

export default function Player() {
  const project = useStore((s) => s.project);
  const playing = useStore((s) => s.playing);
  const setPlaying = useStore((s) => s.setPlaying);
  const previewMode = useStore((s) => s.previewMode);
  const videoRef = useRef<HTMLVideoElement>(null);
  const duration = useStore((s) => s.duration());

  // Attach the video to the imperative controller.
  useEffect(() => {
    player.attach(videoRef.current);
    return () => player.attach(null);
  }, [project?.id]);

  // rAF loop: push currentTime into the clock and, in Edited mode, skip cuts.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) {
        let t = v.currentTime;
        if (previewMode === "edited") {
          const keep = useStore.getState().keepRanges();
          if (keep.length && !contains(keep, t)) {
            const next = nextKeepStart(keep, t);
            if (next === null) {
              // past the last kept span — stop at the end of playable content
              v.pause();
            } else {
              v.currentTime = next;
              t = next;
            }
          }
        }
        clock.set(t);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [previewMode]);

  // Reframe preview: a centered crop frame matching the export aspect.
  const edl = headEdl(project);
  const previewAspect = previewMode === "edited" ? (edl?.aspect ?? "source") : "source";
  const frameAspect =
    previewAspect === "9:16" ? "aspect-[9/16]" : previewAspect === "1:1" ? "aspect-square" : "";
  const isReframed = previewAspect !== "source";

  return (
    <div className="flex flex-col gap-2">
      <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-lg bg-black">
        <div
          className={`relative h-full overflow-hidden ${isReframed ? frameAspect : "w-full"}`}
        >
          {project && (
            <video
              ref={videoRef}
              src={`/media/${project.id}`}
              className={`h-full w-full ${isReframed ? "object-cover" : "object-contain"}`}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onClick={() => player.toggle()}
              playsInline
            />
          )}
          <CaptionOverlay />
        </div>
      </div>

      <div className="flex items-center gap-3 px-1">
        <button
          onClick={() => player.toggle()}
          aria-label={playing ? "Pause" : "Play"}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-ink-700 text-parchment-100 transition hover:bg-ink-600"
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>
        <div className="flex items-center gap-1.5">
          <TimeReadout />
          <span className="tc text-xs text-parchment-600">/ {fmtClock(duration)}</span>
        </div>
      </div>
    </div>
  );
}

function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden>
      <path d="M3 2l9 5-9 5z" />
    </svg>
  );
}
function PauseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden>
      <rect x="3" y="2" width="3" height="10" rx="1" />
      <rect x="8" y="2" width="3" height="10" rx="1" />
    </svg>
  );
}
