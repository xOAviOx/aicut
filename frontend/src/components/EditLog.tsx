import { useStore } from "../store";

export default function EditLog({ onClose }: { onClose: () => void }) {
  const project = useStore((s) => s.project);
  const gotoRevision = useStore((s) => s.gotoRevision);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  if (!project) return null;

  const headIdx = project.revisions.findIndex((r) => r.id === project.head_revision_id);
  const rows = project.revisions.map((r, i) => ({ r, i }));

  return (
    <div className="flex h-full w-80 flex-col border-l border-ink-700/60 bg-ink-850">
      <div className="flex items-center justify-between border-b border-ink-700/60 px-4 py-2.5">
        <span className="font-ui text-xs uppercase tracking-widest text-parchment-600">
          Edit log
        </span>
        <button onClick={onClose} className="text-parchment-500 hover:text-parchment-100">
          ✕
        </button>
      </div>

      <div className="flex gap-2 border-b border-ink-700/50 px-4 py-2">
        <button
          onClick={undo}
          disabled={headIdx <= 0}
          className="flex-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-parchment-200 transition hover:border-accent disabled:opacity-40"
        >
          ↶ Undo
        </button>
        <button
          onClick={redo}
          disabled={headIdx >= project.revisions.length - 1}
          className="flex-1 rounded-md border border-ink-600 px-2 py-1 text-xs text-parchment-200 transition hover:border-accent disabled:opacity-40"
        >
          ↷ Redo
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {rows
          .slice()
          .reverse()
          .map(({ r, i }) => {
            const isHead = i === headIdx;
            const isFuture = i > headIdx;
            return (
              <button
                key={r.id}
                onClick={() => gotoRevision(r.id)}
                className={`mb-1 block w-full rounded-md px-3 py-2 text-left transition ${
                  isHead
                    ? "bg-accent/15 ring-1 ring-accent/40"
                    : isFuture
                      ? "opacity-45 hover:opacity-80"
                      : "hover:bg-ink-800"
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-ui text-xs text-parchment-100">{r.label}</span>
                  {isHead && <span className="tc text-[10px] text-accent">head</span>}
                </div>
                {r.notes && (
                  <div className="mt-0.5 truncate font-reading text-[11px] italic text-parchment-500">
                    {r.notes}
                  </div>
                )}
              </button>
            );
          })}
      </div>
    </div>
  );
}
