// Timecode + duration formatting helpers.

export function fmtClock(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const total = Math.floor(seconds);
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
  return `${m}:${pad(s)}`;
}

// Compact "14:32 -> 11:07, -23%" style duration delta.
export function fmtDelta(sourceDur: number, outputDur: number): string {
  const pct = sourceDur > 0 ? Math.round(((outputDur - sourceDur) / sourceDur) * 100) : 0;
  return `${fmtClock(sourceDur)} → ${fmtClock(outputDur)}, ${pct}%`;
}

export function fmtSignedDuration(seconds: number): string {
  const sign = seconds < 0 ? "−" : "+";
  return `${sign}${fmtClock(Math.abs(seconds))}`;
}
