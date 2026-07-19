import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { api } from "../api";
import { fmtClock } from "../lib/format";
import type { Project, Workspace } from "../types";

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
  const openWorkspace = useStore((s) => s.openWorkspace);
  const [path, setPath] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [workspaces, setWorkspaces] = useState<{ workspace: Workspace; clips: Project[] }[]>([]);
  const [showNew, setShowNew] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadWorkspaces = () => api.listWorkspaces().then(setWorkspaces).catch(() => setWorkspaces([]));

  useEffect(() => {
    init();
    loadWorkspaces();
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
        <h2 className="font-ui text-sm uppercase tracking-widest text-parchment-600">Workspaces</h2>
        <button
          onClick={() => setShowNew(true)}
          className="rounded-md border border-ink-600 px-3 py-1 text-xs text-parchment-200 transition hover:border-accent"
        >
          + New workspace
        </button>
      </div>
      {workspaces.length === 0 ? (
        <p className="mt-2 text-sm text-parchment-600">
          None yet — group two or more clips to edit and export them together.
        </p>
      ) : (
        <div className="mt-3 grid auto-rows-min grid-cols-2 gap-3 md:grid-cols-3">
          {workspaces.map((w) => (
            <button
              key={w.workspace.id}
              onClick={() => openWorkspace(w.workspace.id)}
              className="rounded-lg border border-ink-700/70 bg-ink-800 px-4 py-3 text-left transition hover:border-accent/60"
            >
              <div className="truncate font-ui text-sm text-parchment-100">{w.workspace.name}</div>
              <div className="tc mt-1 text-[11px] text-parchment-500">
                {w.clips.length} clip{w.clips.length !== 1 ? "s" : ""}
              </div>
            </button>
          ))}
        </div>
      )}

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

      {showNew && (
        <NewWorkspaceDialog
          projects={projects.filter((p) => p.transcript_status === "ready")}
          onClose={() => setShowNew(false)}
          onCreated={(id) => {
            setShowNew(false);
            loadWorkspaces();
            openWorkspace(id);
          }}
        />
      )}
    </div>
  );
}

function NewWorkspaceDialog({
  projects,
  onClose,
  onCreated,
}: {
  projects: Project[];
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const create = async () => {
    if (selected.length < 1) return;
    setCreating(true);
    setErr(null);
    try {
      const wp = await api.createWorkspace({
        name: name.trim() || "Workspace",
        clip_ids: selected,
      });
      onCreated(wp.workspace.id);
    } catch (e) {
      setErr(String(e));
      setCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[460px] max-w-full rounded-xl border border-ink-700 bg-ink-850 p-5 shadow-2xl"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-ui text-sm font-semibold text-parchment-100">New workspace</h2>
          <button onClick={onClose} className="text-parchment-500 hover:text-parchment-100">
            ✕
          </button>
        </div>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Workspace name"
          className="mt-3 w-full rounded-md border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-parchment-100 outline-none focus:border-accent"
        />
        <div className="mt-3 mb-1.5 text-xs uppercase tracking-wide text-parchment-600">
          Pick clips (in order)
        </div>
        {projects.length === 0 ? (
          <p className="text-sm text-parchment-600">
            No ready clips yet. Import a couple of videos first, then group them.
          </p>
        ) : (
          <div className="max-h-56 space-y-1 overflow-y-auto">
            {projects.map((p) => {
              const order = selected.indexOf(p.id);
              const active = order >= 0;
              return (
                <button
                  key={p.id}
                  onClick={() => toggle(p.id)}
                  className={`flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs transition ${
                    active
                      ? "border-accent bg-accent/10 text-parchment-100"
                      : "border-ink-700 text-parchment-300 hover:border-accent/50"
                  }`}
                >
                  <span className="truncate">{p.name || p.id}</span>
                  <span className="tc ml-2 shrink-0 text-parchment-500">
                    {active ? `#${order + 1}` : "add"}
                  </span>
                </button>
              );
            })}
          </div>
        )}
        {err && <p className="mt-2 text-xs text-redact">{err}</p>}
        <button
          onClick={create}
          disabled={creating || selected.length < 1}
          className="mt-4 w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-ink-900 transition hover:bg-accent-glow disabled:opacity-50"
        >
          {creating ? "Creating…" : `Create workspace${selected.length ? ` (${selected.length} clips)` : ""}`}
        </button>
      </div>
    </div>
  );
}
