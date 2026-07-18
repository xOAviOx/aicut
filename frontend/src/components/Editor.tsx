import { useEffect, useState } from "react";
import { useStore, headEdl } from "../store";
import Player from "./Player";
import Transcript from "./Transcript";
import Timeline from "./Timeline";
import EditLog from "./EditLog";
import CommandBar from "./CommandBar";
import ExportDialog from "./ExportDialog";
import Shortcuts from "./Shortcuts";
import { total } from "../lib/rangemath";
import { fmtClock } from "../lib/format";
import { useKeyboard } from "../hooks/useKeyboard";

function ErrorBanner() {
  const error = useStore((s) => s.error);
  const clearError = useStore((s) => s.clearError);
  if (!error) return null;
  return (
    <div className="flex items-center justify-between gap-3 border-b border-redact/40 bg-redact/15 px-4 py-2">
      <span className="text-sm text-parchment-100">{error}</span>
      <button onClick={clearError} className="text-parchment-400 hover:text-parchment-100">
        ✕
      </button>
    </div>
  );
}

function TranscribingOverlay() {
  const status = useStore((s) => s.liveStatus);
  const progress = useStore((s) => s.liveProgress);
  const error = useStore((s) => s.project?.transcript_error);
  if (status === "ready") return null;
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-ink-900/85 backdrop-blur-sm">
      <div className="w-80 text-center">
        {status === "error" ? (
          <>
            <p className="font-reading text-lg text-redact">Transcription failed</p>
            <p className="mt-2 text-sm text-parchment-400">{error}</p>
          </>
        ) : (
          <>
            <p className="font-reading text-lg text-parchment-100">
              {status === "running" ? "Transcribing…" : "Queued…"}
            </p>
            <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full rounded-full bg-accent transition-[width] duration-300"
                style={{ width: `${Math.round((progress || 0) * 100)}%` }}
              />
            </div>
            <p className="tc mt-2 text-xs text-parchment-600">
              {Math.round((progress || 0) * 100)}%
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function PreviewToggle() {
  const previewMode = useStore((s) => s.previewMode);
  const toggle = useStore((s) => s.togglePreviewMode);
  const project = useStore((s) => s.project);
  const duration = useStore((s) => s.duration());
  const edl = headEdl(project);
  const output = edl ? total(edl.keep) : duration;
  const pct = duration > 0 ? Math.round(((output - duration) / duration) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="tc text-xs text-parchment-400">
        {fmtClock(duration)} <span className="text-parchment-600">→</span>{" "}
        <span className="text-parchment-100">{fmtClock(output)}</span>
        {pct !== 0 && <span className="ml-1 text-accent">{pct}%</span>}
      </div>
      <button
        onClick={toggle}
        className="rounded-md border border-ink-600 px-2.5 py-1 text-xs text-parchment-200 transition hover:border-accent"
        title="Toggle Edited / Original preview (E)"
      >
        {previewMode === "edited" ? "Edited" : "Original"}
      </button>
    </div>
  );
}

function HeaderControls({ onToggleLog }: { onToggleLog: () => void }) {
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const project = useStore((s) => s.project);
  const headIdx = project
    ? project.revisions.findIndex((r) => r.id === project.head_revision_id)
    : -1;
  const canUndo = headIdx > 0;
  const canRedo = project ? headIdx < project.revisions.length - 1 : false;
  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={undo}
        disabled={!canUndo}
        title="Undo (Ctrl/Cmd+Z)"
        className="rounded-md px-2 py-1 text-sm text-parchment-300 transition hover:bg-ink-700 disabled:opacity-30"
      >
        ↶
      </button>
      <button
        onClick={redo}
        disabled={!canRedo}
        title="Redo (Shift+Ctrl/Cmd+Z)"
        className="rounded-md px-2 py-1 text-sm text-parchment-300 transition hover:bg-ink-700 disabled:opacity-30"
      >
        ↷
      </button>
      <button
        onClick={onToggleLog}
        title="Edit log"
        className="ml-1 rounded-md border border-ink-600 px-2.5 py-1 text-xs text-parchment-200 transition hover:border-accent"
      >
        History
      </button>
    </div>
  );
}

export default function Editor() {
  const project = useStore((s) => s.project);
  const closeProject = useStore((s) => s.closeProject);
  const [showLog, setShowLog] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  useKeyboard();
  useEffect(() => {
    const open = () => setShowHelp(true);
    window.addEventListener("aicut:help", open);
    return () => window.removeEventListener("aicut:help", open);
  }, []);
  if (!project) return null;

  return (
    <div className="relative flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-ink-700/60 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <button
            onClick={closeProject}
            className="rounded-md px-2 py-1 text-sm text-parchment-400 transition hover:text-parchment-100"
          >
            ← Library
          </button>
          <span className="font-ui text-sm font-medium text-parchment-100">{project.name}</span>
        </div>
        <div className="flex items-center gap-4">
          <PreviewToggle />
          <HeaderControls onToggleLog={() => setShowLog((v) => !v)} />
          <button
            onClick={() => setShowExport(true)}
            className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-ink-900 transition hover:bg-accent-glow"
          >
            Export
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[minmax(360px,42%)_1fr]">
          <div className="flex min-h-0 flex-col gap-3 border-r border-ink-700/50 p-4">
            <Player />
            <Timeline />
          </div>
          <div className="flex min-h-0 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 overflow-hidden">
              <Transcript />
            </div>
            <CommandBar />
          </div>
        </div>
        {showLog && <EditLog onClose={() => setShowLog(false)} />}
      </div>

      <TranscribingOverlay />
      {showExport && <ExportDialog onClose={() => setShowExport(false)} />}
    </div>
  );
}
