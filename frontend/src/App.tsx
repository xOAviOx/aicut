import { useEffect } from "react";
import { useStore } from "./store";
import Library from "./components/Library";
import Editor from "./components/Editor";
import WorkspaceBar from "./components/WorkspaceBar";

export default function App() {
  const view = useStore((s) => s.view);
  const workspace = useStore((s) => s.workspace);
  const openProject = useStore((s) => s.openProject);
  const openWorkspace = useStore((s) => s.openWorkspace);

  // Deep-links: /?open=<projectId> or /?workspace=<workspaceId>.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const wid = params.get("workspace");
    const id = params.get("open");
    if (wid) openWorkspace(wid);
    else if (id) openProject(id);
  }, [openProject, openWorkspace]);
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
        <div className="flex h-full min-h-0 flex-col">
          {workspace && <WorkspaceBar />}
          <div className="min-h-0 flex-1">
            <Editor />
          </div>
        </div>
      )}
    </div>
  );
}
