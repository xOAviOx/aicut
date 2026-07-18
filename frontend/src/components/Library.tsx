import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { fmtClock } from "../lib/format";
import type { Project } from "../types";

const STATUS_LABEL: Record<string, string> = {
  pending: "queued",
  running: "transcribing…",
  ready: "ready",
  error: "error",
};

function StatusChip({ p }: { p: Project }) {
  const color =
    p.transcript_status === "ready"
      ? "text-accent"
      : p.transcript_status === "error"
        ? "text-redact"
        : "text-parchment-400";
  return (
    <span className={`tc text-[11px] uppercase tracking-wide ${color}`}>
      {STATUS_LABEL[p.transcript_status] ?? p.transcript_status}
    </span>
  );
}

export default function Library() {
  const { projects, loadingLibrary, init, createFromPath, uploadFile, openProject, deleteProject, busy, error } =
    useStore();
  const [path, setPath] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    init();
  }, [init]);

  const submitPath = () => {
    if (path.trim()) createFromPath(path.trim());
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-5xl flex-col px-8 py-8">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) uploadFile(f);
        }}
        className={`rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
          dragOver ? "border-accent bg-ink-800/60" : "border-ink-600/70 bg-ink-850/40"
        }`}
      >
        <p className="font-reading text-2xl text-parchment-200">Drop a video to start</p>
        <p className="mt-1 text-sm text-parchment-600">
          or paste a file path — the video is imported in place, no copy
        </p>
        <div className="mx-auto mt-5 flex max-w-xl items-center gap-2">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitPath()}
            placeholder="/path/to/talk.mp4"
            className="tc flex-1 rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-parchment-100 outline-none focus:border-accent"
          />
          <button
            onClick={submitPath}
            disabled={busy}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-ink-900 transition hover:bg-accent-glow disabled:opacity-50"
          >
            Import
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            className="rounded-md border border-ink-600 px-4 py-2 text-sm text-parchment-200 hover:border-accent"
          >
            Upload
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="video/*,audio/*"
            hidden
            onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])}
          />
        </div>
        {error && <p className="mt-3 text-sm text-redact">{error}</p>}
      </div>

      <div className="mt-8 flex items-baseline justify-between">
        <h2 className="font-ui text-sm uppercase tracking-widest text-parchment-600">Projects</h2>
        {loadingLibrary && <span className="text-xs text-parchment-600">loading…</span>}
      </div>

      <div className="mt-3 grid flex-1 auto-rows-min grid-cols-2 gap-3 overflow-y-auto md:grid-cols-3">
        {projects.length === 0 && !loadingLibrary && (
          <p className="col-span-full py-10 text-center text-sm text-parchment-600">
            No projects yet.
          </p>
        )}
        {projects.map((p) => (
          <button
            key={p.id}
            onClick={() => openProject(p.id)}
            className="group relative overflow-hidden rounded-lg border border-ink-700/70 bg-ink-800 text-left transition hover:border-accent/60"
          >
            <div className="flex aspect-video items-center justify-center bg-ink-900">
              {p.thumbnail ? (
                <img src={p.thumbnail} alt="" className="h-full w-full object-cover" />
              ) : (
                <span className="font-reading text-3xl text-ink-500">aic</span>
              )}
            </div>
            <div className="flex items-center justify-between px-3 py-2">
              <div className="min-w-0">
                <div className="truncate font-ui text-sm text-parchment-100">{p.name}</div>
                <div className="mt-0.5 flex items-center gap-2">
                  <StatusChip p={p} />
                  {p.duration > 0 && (
                    <span className="tc text-[11px] text-parchment-600">
                      {fmtClock(p.duration)}
                    </span>
                  )}
                </div>
              </div>
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  deleteProject(p.id);
                }}
                className="ml-2 shrink-0 rounded px-1.5 py-0.5 text-xs text-parchment-600 opacity-0 transition hover:text-redact group-hover:opacity-100"
              >
                ✕
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
