const SHORTCUTS: [string, string][] = [
  ["Space", "Play / pause"],
  ["Click word", "Seek to that word"],
  ["Drag / Shift-click", "Select a span of words"],
  ["Delete / Backspace", "Cut the selected words"],
  ["Ctrl/⌘ + Z", "Undo"],
  ["Shift + Ctrl/⌘ + Z", "Redo"],
  ["← / →", "Nudge 1 second"],
  ["E", "Toggle Edited / Original preview"],
  ["?", "This help"],
];

export default function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[380px] max-w-full rounded-xl border border-ink-700 bg-ink-850 p-5 shadow-2xl"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-ui text-sm font-semibold text-parchment-100">Keyboard shortcuts</h2>
          <button onClick={onClose} className="text-parchment-500 hover:text-parchment-100">
            ✕
          </button>
        </div>
        <dl className="mt-4 space-y-2">
          {SHORTCUTS.map(([key, desc]) => (
            <div key={key} className="flex items-center justify-between gap-4">
              <dt className="tc rounded border border-ink-600 bg-ink-800 px-2 py-0.5 text-xs text-parchment-200">
                {key}
              </dt>
              <dd className="flex-1 text-right text-sm text-parchment-400">{desc}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
