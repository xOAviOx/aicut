import { useEffect, useState } from "react";
import { useStore, headEdl } from "../store";
import { api } from "../api";
import type { Aspect, CaptionGranularity, Project } from "../types";

function fmtSize(bytes: number): string {
  if (bytes > 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes > 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export default function ExportDialog({ onClose }: { onClose: () => void }) {
  const project = useStore((s) => s.project);
  const edl = headEdl(project);
  const startExport = useStore((s) => s.startExport);
  const loadExports = useStore((s) => s.loadExports);
  const status = useStore((s) => s.exportStatus);
  const progress = useStore((s) => s.exportProgress);
  const error = useStore((s) => s.exportError);
  const exports = useStore((s) => s.exports);

  // Prefer the project's last-used export options, falling back to the current
  // edit's aspect/captions so first-time exports still make sense.
  const saved = project?.settings.export_preset;
  const [aspect, setAspect] = useState<Aspect>(saved?.aspect ?? edl?.aspect ?? "source");
  const [captions, setCaptions] = useState<boolean>(
    saved?.captions ?? edl?.captions.enabled ?? false,
  );
  const [granularity, setGranularity] = useState<CaptionGranularity>(
    saved?.granularity ?? edl?.captions.granularity ?? "segment",
  );
  const [quality, setQuality] = useState(saved?.quality ?? "balanced");

  // Other ready projects that can be stitched after this one.
  const [others, setOthers] = useState<Project[]>([]);
  const [appendIds, setAppendIds] = useState<string[]>([]);

  useEffect(() => {
    loadExports();
    api
      .listProjects()
      .then((ps) =>
        setOthers(ps.filter((p) => p.id !== project?.id && p.transcript_status === "ready")),
      )
      .catch(() => setOthers([]));
  }, [loadExports, project?.id]);

  const toggleAppend = (id: string) =>
    setAppendIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));

  const run = () =>
    startExport({ aspect, captions, granularity, quality, append_project_ids: appendIds });

  const Radio = ({
    active,
    onClick,
    children,
  }: {
    active: boolean;
    onClick: () => void;
    children: React.ReactNode;
  }) => (
    <button
      onClick={onClick}
      className={`rounded-md border px-3 py-1.5 text-xs transition ${
        active
          ? "border-accent bg-accent/15 text-accent"
          : "border-ink-600 text-parchment-300 hover:border-accent/50"
      }`}
    >
      {children}
    </button>
  );

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[440px] max-w-full rounded-xl border border-ink-700 bg-ink-850 p-5 shadow-2xl"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-ui text-sm font-semibold text-parchment-100">Export</h2>
          <button onClick={onClose} className="text-parchment-500 hover:text-parchment-100">
            ✕
          </button>
        </div>

        <div className="mt-4 space-y-4">
          <div>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-parchment-600">Aspect</div>
            <div className="flex gap-2">
              <Radio active={aspect === "source"} onClick={() => setAspect("source")}>
                Source
              </Radio>
              <Radio active={aspect === "9:16"} onClick={() => setAspect("9:16")}>
                9:16
              </Radio>
              <Radio active={aspect === "1:1"} onClick={() => setAspect("1:1")}>
                1:1
              </Radio>
            </div>
          </div>

          <div>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-parchment-600">
              Captions
            </div>
            <div className="flex items-center gap-2">
              <Radio active={captions} onClick={() => setCaptions(true)}>
                On
              </Radio>
              <Radio active={!captions} onClick={() => setCaptions(false)}>
                Off
              </Radio>
              {captions && (
                <>
                  <span className="mx-1 text-ink-500">·</span>
                  <Radio
                    active={granularity === "segment"}
                    onClick={() => setGranularity("segment")}
                  >
                    Segment
                  </Radio>
                  <Radio active={granularity === "word"} onClick={() => setGranularity("word")}>
                    Word
                  </Radio>
                </>
              )}
            </div>
          </div>

          <div>
            <div className="mb-1.5 text-xs uppercase tracking-wide text-parchment-600">Quality</div>
            <div className="flex gap-2">
              {["high", "balanced", "fast"].map((q) => (
                <Radio key={q} active={quality === q} onClick={() => setQuality(q)}>
                  {q[0].toUpperCase() + q.slice(1)}
                </Radio>
              ))}
            </div>
          </div>

          {others.length > 0 && (
            <div>
              <div className="mb-1.5 text-xs uppercase tracking-wide text-parchment-600">
                Append clips
              </div>
              <div className="max-h-32 space-y-1 overflow-y-auto">
                {others.map((p) => {
                  const order = appendIds.indexOf(p.id);
                  const active = order >= 0;
                  return (
                    <button
                      key={p.id}
                      onClick={() => toggleAppend(p.id)}
                      className={`flex w-full items-center justify-between rounded-md border px-3 py-1.5 text-xs transition ${
                        active
                          ? "border-accent bg-accent/10 text-parchment-100"
                          : "border-ink-700 text-parchment-300 hover:border-accent/50"
                      }`}
                    >
                      <span className="truncate">{p.name || p.id}</span>
                      <span className="tc ml-2 shrink-0 text-parchment-500">
                        {active ? `#${order + 2}` : "add"}
                      </span>
                    </button>
                  );
                })}
              </div>
              {appendIds.length > 0 && (
                <p className="mt-1.5 text-[11px] text-parchment-500">
                  Stitched after this clip (#1), normalized to the aspect above.
                </p>
              )}
            </div>
          )}
        </div>

        {status === "running" && (
          <div className="mt-4">
            <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
              <div
                className="h-full rounded-full bg-accent transition-[width]"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
            <div className="tc mt-1 text-xs text-parchment-500">
              Rendering… {Math.round(progress * 100)}%
            </div>
          </div>
        )}
        {status === "error" && <p className="mt-3 text-xs text-redact">{error}</p>}

        <button
          onClick={run}
          disabled={status === "running"}
          className="mt-4 w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-ink-900 transition hover:bg-accent-glow disabled:opacity-50"
        >
          {status === "running"
            ? "Exporting…"
            : appendIds.length > 0
              ? `Export merged video (${appendIds.length + 1} clips)`
              : "Export video"}
        </button>

        {exports.length > 0 && (
          <div className="mt-4 border-t border-ink-700/60 pt-3">
            <div className="mb-1.5 text-xs uppercase tracking-wide text-parchment-600">
              Finished
            </div>
            <div className="max-h-40 space-y-1 overflow-y-auto">
              {exports.map((f) => (
                <a
                  key={f.name}
                  href={f.url}
                  download
                  className="flex items-center justify-between rounded-md border border-ink-700 bg-ink-800 px-3 py-1.5 text-xs text-parchment-200 transition hover:border-accent"
                >
                  <span className="truncate">{f.name}</span>
                  <span className="tc ml-2 shrink-0 text-parchment-500">{fmtSize(f.size)}</span>
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
