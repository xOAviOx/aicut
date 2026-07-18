import { useEffect } from "react";
import { useStore } from "./store";
import Library from "./components/Library";
import Editor from "./components/Editor";

export default function App() {
  const view = useStore((s) => s.view);
  const openProject = useStore((s) => s.openProject);

  // Deep-link: /?open=<projectId> jumps straight into the editor.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("open");
    if (id) openProject(id);
  }, [openProject]);
  return (
    <div className="flex h-full flex-col bg-ink-900">
      {view === "library" ? (
        <>
          <header className="flex items-center gap-3 border-b border-ink-700/60 px-5 py-3">
            <span className="font-ui text-lg font-semibold tracking-tight text-parchment-100">
              ai<span className="text-accent">cut</span>
            </span>
            <span className="tc text-xs text-parchment-600">v0.1</span>
          </header>
          <main className="flex-1 overflow-hidden">
            <Library />
          </main>
        </>
      ) : (
        <Editor />
      )}
    </div>
  );
}
