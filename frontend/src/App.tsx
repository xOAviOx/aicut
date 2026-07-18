// M0 shell. The Library + Editor screens are built out in M2+.
export default function App() {
  return (
    <div className="flex h-full flex-col bg-ink-900">
      <header className="flex items-center gap-3 border-b border-ink-700/60 px-5 py-3">
        <span className="font-ui text-lg font-semibold tracking-tight text-parchment-100">
          ai<span className="text-accent">cut</span>
        </span>
        <span className="tc text-xs text-parchment-600">v0.1</span>
      </header>
      <main className="flex flex-1 items-center justify-center">
        <div className="text-center">
          <p className="font-reading text-2xl text-parchment-200">Drop a video to start</p>
          <p className="mt-2 text-sm text-parchment-600">
            The editor arrives in milestone M2.
          </p>
        </div>
      </main>
    </div>
  );
}
