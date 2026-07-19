import { useState } from "react";
import { useStore, headEdl } from "../store";
import { total } from "../lib/rangemath";
import { fmtClock } from "../lib/format";

// Sum of every clip's *edited* output length — the length of the stitched export.
function useCombinedDuration(): number {
  const clips = useStore((s) => s.workspaceClips);
  return clips.reduce((acc, p) => {
    const edl = headEdl(p);
    return acc + (edl ? total(edl.keep) : p.duration || 0);
  }, 0);
}

function ExportMerged() {
  const workspace = useStore((s) => s.workspace);
  const exportWorkspace = useStore((s) => s.exportWorkspace);
  const status = useStore((s) => s.exportStatus);
  const progress = useStore((s) => s.exportProgress);
  const error = useStore((s) => s.exportError);
  const url = useStore((s) => s.workspaceExportUrl);
  const [open, setOpen] = useState(false);
  const [aspect, setAspect] = useState("source");
  const [captions, setCaptions] = useState(false);
  const [quality, setQuality] = useState("balanced");
  const n = workspace?.clip_ids.length ?? 0;

  const Chip = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) => (
    <button
      onClick={onClick}
      className={`rounded-md border px-2 py-1 text-[11px] transition ${
        active ? "border-accent bg-accent/15 text-accent" : "border-ink-600 text-parchment-300 hover:border-accent/50"
      }`}
    >
      {children}
    </button>
  );

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={n < 2}
        title={n < 2 ? "Add a second clip to merge" : "Stitch all clips into one file"}
        className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-ink-900 transition hover:bg-accent-glow disabled:opacity-40"
      >
        Export merged{n > 1 ? ` (${n})` : ""}
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-50 w-72 rounded-lg border border-ink-700 bg-ink-850 p-3 shadow-2xl">
          <div className="mb-2 text-[11px] uppercase tracking-wide text-parchment-600">Aspect</div>
          <div className="flex gap-1.5">
            {["source", "9:16", "1:1"].map((a) => (
              <Chip key={a} active={aspect === a} onClick={() => setAspect(a)}>
                {a}
              </Chip>
            ))}
          </div>
          <div className="mb-2 mt-3 text-[11px] uppercase tracking-wide text-parchment-600">Quality</div>
          <div className="flex items-center justify-between">
            <div className="flex gap-1.5">
              {["high", "balanced", "fast"].map((q) => (
                <Chip key={q} active={quality === q} onClick={() => setQuality(q)}>
                  {q}
                </Chip>
              ))}
            </div>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs text-parchment-300">
              <input type="checkbox" checked={captions} onChange={() => setCaptions((v) => !v)} className="accent-accent" />
              captions
            </label>
          </div>

          {status === "running" && (
            <div className="mt-3">
              <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
                <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
              <div className="tc mt-1 text-[11px] text-parchment-500">Stitching… {Math.round(progress * 100)}%</div>
            </div>
          )}
          {status === "error" && <p className="mt-2 text-[11px] text-redact">{error}</p>}
          {status === "done" && url && (
            <a
              href={url}
              download
              className="mt-3 block rounded-md border border-accent/60 bg-accent/10 px-3 py-1.5 text-center text-xs text-parchment-100 hover:bg-accent/20"
            >
              Download merged video ↓
            </a>
          )}

          <button
            onClick={() => exportWorkspace({ aspect, captions, granularity: "segment", quality })}
            disabled={status === "running" || n < 2}
            className="mt-3 w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-ink-900 transition hover:bg-accent-glow disabled:opacity-50"
          >
            {status === "running" ? "Stitching…" : `Stitch & export ${n} clips`}
          </button>
        </div>
      )}
    </div>
  );
}

export default function WorkspaceBar() {
  const workspace = useStore((s) => s.workspace);
  const clips = useStore((s) => s.workspaceClips);
  const activeId = useStore((s) => s.project?.id);
  const selectClip = useStore((s) => s.selectClip);
  const removeClip = useStore((s) => s.removeClipFromWorkspace);
  const addClip = useStore((s) => s.addClipToWorkspace);
  const closeProject = useStore((s) => s.closeProject);
  const combined = useCombinedDuration();
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  if (!workspace) return null;

  const submitAdd = () => {
    if (path.trim()) {
      addClip(path.trim());
      setPath("");
      setAdding(false);
    }
  };

  return (
    <div className="flex items-center gap-3 border-b border-ink-700/60 bg-ink-850/60 px-4 py-2">
      <button
        onClick={closeProject}
        className="rounded-md px-2 py-1 text-sm text-parchment-400 transition hover:text-parchment-100"
      >
        ← Library
      </button>
      <span className="font-ui text-sm font-medium text-parchment-100">{workspace.name}</span>

      <div className="flex flex-1 items-center gap-1.5 overflow-x-auto">
        {clips.map((c, i) => {
          const active = c.id === activeId;
          return (
            <div
              key={c.id}
              className={`group flex shrink-0 items-center rounded-md border px-2 py-1 text-xs transition ${
                active
                  ? "border-accent bg-accent/15 text-parchment-100"
                  : "border-ink-600 text-parchment-300 hover:border-accent/50"
              }`}
            >
              <button onClick={() => selectClip(c.id)} className="flex items-center gap-1.5">
                <span className="tc text-parchment-500">{i + 1}</span>
                <span className="max-w-[10rem] truncate">{c.name || c.id}</span>
                {c.transcript_status !== "ready" && (
                  <span className="tc text-[10px] text-parchment-500">
                    {c.transcript_status === "error" ? "err" : "…"}
                  </span>
                )}
              </button>
              {clips.length > 1 && (
                <button
                  onClick={() => removeClip(c.id)}
                  title="Remove clip from workspace"
                  className="ml-1.5 text-parchment-600 opacity-0 transition hover:text-redact group-hover:opacity-100"
                >
                  ✕
                </button>
              )}
            </div>
          );
        })}
        {adding ? (
          <input
            autoFocus
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitAdd();
              if (e.key === "Escape") setAdding(false);
            }}
            onBlur={() => setAdding(false)}
            placeholder="/path/to/next-clip.mp4"
            className="tc w-56 shrink-0 rounded-md border border-ink-600 bg-ink-900 px-2 py-1 text-xs text-parchment-100 outline-none focus:border-accent"
          />
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="shrink-0 rounded-md border border-dashed border-ink-600 px-2 py-1 text-xs text-parchment-400 transition hover:border-accent hover:text-parchment-100"
          >
            + clip
          </button>
        )}
      </div>

      <div className="tc shrink-0 text-xs text-parchment-400">
        combined <span className="text-parchment-100">{fmtClock(combined)}</span>
      </div>
      <ExportMerged />
    </div>
  );
}
