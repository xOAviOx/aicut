import { create } from "zustand";
import { api, type ProjectPayload } from "./api";
import { clock } from "./lib/clock";
import type { CompiledEDL, Project, Span, Transcript, WordRef } from "./types";
import { coordsToWordRefs, type WordCoord } from "./lib/transcriptSelection";

export type PreviewMode = "edited" | "original";

export function headEdl(project: Project | null): CompiledEDL | null {
  if (!project || !project.head_revision_id) return null;
  const rev = project.revisions.find((r) => r.id === project.head_revision_id);
  return rev?.edl ?? null;
}

interface State {
  view: "library" | "editor";
  projects: Project[];
  project: Project | null;
  transcript: Transcript | null;
  loadingLibrary: boolean;
  busy: boolean;
  error: string | null;

  previewMode: PreviewMode;
  follow: boolean;
  playing: boolean;
  showCutText: boolean;

  // transcript selection (word coords), M3
  selection: WordCoord[];
  selectionAnchor: number | null;

  liveStatus: string | null;
  liveProgress: number;

  commandPending: boolean;
  commandError: string | null;
  lastCommand: { summary: string; notes: string } | null;

  exportStatus: "idle" | "running" | "done" | "error";
  exportProgress: number;
  exportError: string | null;
  exports: { name: string; url: string; size: number }[];

  _unsub: (() => void) | null;

  // derived
  keepRanges: () => Span[];
  duration: () => number;

  // actions
  init: () => Promise<void>;
  openProject: (id: string) => Promise<void>;
  closeProject: () => void;
  createFromPath: (path: string) => Promise<void>;
  uploadFile: (file: File) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  refresh: () => Promise<void>;
  applyPayload: (p: ProjectPayload) => void;

  setPreviewMode: (m: PreviewMode) => void;
  togglePreviewMode: () => void;
  toggleFollow: () => void;
  toggleShowCutText: () => void;
  setPlaying: (p: boolean) => void;

  setSelection: (coords: WordCoord[], anchor?: number | null) => void;
  clearSelection: () => void;
  selectedWordRefs: () => WordRef[];

  applyAction: (action: unknown, notes?: string) => Promise<void>;
  cutSelection: () => Promise<void>;
  restoreSelection: () => Promise<void>;
  oneClick: (kind: string) => Promise<void>;
  command: (instruction: string) => Promise<void>;
  dismissCommandError: () => void;
  clearError: () => void;

  startExport: (preset: { aspect?: string; captions?: boolean; quality: string }) => Promise<void>;
  loadExports: () => Promise<void>;

  undo: () => Promise<void>;
  redo: () => Promise<void>;
  gotoRevision: (revId: string) => Promise<void>;
}

export const useStore = create<State>((set, get) => ({
  view: "library",
  projects: [],
  project: null,
  transcript: null,
  loadingLibrary: false,
  busy: false,
  error: null,

  previewMode: "edited",
  follow: true,
  playing: false,
  showCutText: true,

  selection: [],
  selectionAnchor: null,

  liveStatus: null,
  liveProgress: 0,

  commandPending: false,
  commandError: null,
  lastCommand: null,

  exportStatus: "idle",
  exportProgress: 0,
  exportError: null,
  exports: [],

  _unsub: null,

  keepRanges: () => {
    const { project, transcript, previewMode } = get();
    const dur = transcript?.duration ?? project?.duration ?? 0;
    if (previewMode === "original") return [[0, dur]];
    const edl = headEdl(project);
    return edl ? edl.keep : [[0, dur]];
  },
  duration: () => get().transcript?.duration ?? get().project?.duration ?? 0,

  init: async () => {
    set({ loadingLibrary: true, error: null });
    try {
      const projects = await api.listProjects();
      set({ projects, loadingLibrary: false });
    } catch (e) {
      set({ error: String(e), loadingLibrary: false });
    }
  },

  openProject: async (id) => {
    get()._unsub?.();
    set({ busy: true, error: null });
    try {
      const payload = await api.getProject(id);
      get().applyPayload(payload);
      clock.set(0);
      clock.duration = payload.transcript?.duration ?? payload.project.duration ?? 0;
      set({
        view: "editor",
        busy: false,
        liveStatus: payload.project.transcript_status,
        liveProgress: payload.project.transcript_progress,
        selection: [],
        selectionAnchor: null,
      });
      const unsub = api.events(id, (e, type) => {
        const data = JSON.parse(e.data);
        if (type === "transcription") {
          set({ liveStatus: data.status, liveProgress: data.progress ?? get().liveProgress });
          if (data.status === "ready" || data.status === "error") {
            get().refresh();
          }
        } else if (type === "export") {
          if (data.status === "running") {
            set({ exportStatus: "running", exportProgress: data.progress ?? 0 });
          } else if (data.status === "done") {
            set({ exportStatus: "done", exportProgress: 1 });
            get().loadExports();
          } else if (data.status === "error") {
            set({ exportStatus: "error", exportError: data.error ?? "export failed" });
          }
        }
      });
      set({ _unsub: unsub });
    } catch (e) {
      set({ error: String(e), busy: false });
    }
  },

  closeProject: () => {
    get()._unsub?.();
    set({ view: "library", project: null, transcript: null, _unsub: null });
    get().init();
  },

  createFromPath: async (path) => {
    set({ busy: true, error: null });
    try {
      const project = await api.createProject(path);
      set({ busy: false });
      await get().openProject(project.id);
    } catch (e) {
      set({ error: String(e), busy: false });
    }
  },

  uploadFile: async (file) => {
    set({ busy: true, error: null });
    try {
      const project = await api.uploadProject(file);
      set({ busy: false });
      await get().openProject(project.id);
    } catch (e) {
      set({ error: String(e), busy: false });
    }
  },

  deleteProject: async (id) => {
    await api.deleteProject(id);
    await get().init();
  },

  refresh: async () => {
    const { project } = get();
    if (!project) return;
    try {
      const payload = await api.getProject(project.id);
      get().applyPayload(payload);
    } catch (e) {
      set({ error: String(e) });
    }
  },

  applyPayload: (payload) => {
    set({ project: payload.project, transcript: payload.transcript });
    if (payload.transcript) clock.duration = payload.transcript.duration;
  },

  setPreviewMode: (m) => set({ previewMode: m }),
  togglePreviewMode: () =>
    set({ previewMode: get().previewMode === "edited" ? "original" : "edited" }),
  toggleFollow: () => set({ follow: !get().follow }),
  toggleShowCutText: () => set({ showCutText: !get().showCutText }),
  setPlaying: (p) => set({ playing: p }),

  setSelection: (coords, anchor = null) =>
    set({ selection: coords, selectionAnchor: anchor ?? get().selectionAnchor }),
  clearSelection: () => set({ selection: [], selectionAnchor: null }),
  selectedWordRefs: () => coordsToWordRefs(get().selection),

  applyAction: async (action, notes) => {
    const { project } = get();
    if (!project) return;
    set({ busy: true, error: null });
    try {
      const payload = await api.edit(project.id, action, notes);
      get().applyPayload(payload);
      get().clearSelection();
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ busy: false });
    }
  },
  cutSelection: async () => {
    const refs = get().selectedWordRefs();
    if (!refs.length) return;
    await get().applyAction({ type: "cut_words", word_refs: refs });
  },
  restoreSelection: async () => {
    const refs = get().selectedWordRefs();
    if (!refs.length) return;
    await get().applyAction({ type: "restore_words", word_refs: refs });
  },
  oneClick: async (kind) => {
    const { project } = get();
    if (!project) return;
    set({ busy: true, error: null });
    try {
      const payload = await api.oneClick(project.id, kind);
      get().applyPayload(payload);
      get().clearSelection();
    } catch (e) {
      set({ error: String(e) });
    } finally {
      set({ busy: false });
    }
  },

  command: async (instruction) => {
    const { project } = get();
    if (!project || !instruction.trim()) return;
    set({ commandPending: true, commandError: null });
    try {
      const res = await api.command(project.id, instruction.trim());
      if (res.ok) {
        await get().refresh();
        set({
          lastCommand: { summary: res.summary ?? "", notes: res.notes ?? "" },
          commandError: null,
        });
        get().clearSelection();
      } else {
        set({ commandError: res.error ?? "Couldn't map that to an edit." });
      }
    } catch (e) {
      set({ commandError: String(e) });
    } finally {
      set({ commandPending: false });
    }
  },
  dismissCommandError: () => set({ commandError: null }),
  clearError: () => set({ error: null }),

  startExport: async (preset) => {
    const { project } = get();
    if (!project) return;
    set({ exportStatus: "running", exportProgress: 0, exportError: null });
    try {
      await api.export(project.id, preset);
    } catch (e) {
      set({ exportStatus: "error", exportError: String(e) });
    }
  },
  loadExports: async () => {
    const { project } = get();
    if (!project) return;
    try {
      const { exports } = await api.listExports(project.id);
      set({ exports });
    } catch {
      /* ignore */
    }
  },

  undo: async () => {
    const { project } = get();
    if (!project) return;
    get().applyPayload(await api.undo(project.id));
    get().clearSelection();
  },
  redo: async () => {
    const { project } = get();
    if (!project) return;
    get().applyPayload(await api.redo(project.id));
    get().clearSelection();
  },
  gotoRevision: async (revId) => {
    const { project } = get();
    if (!project) return;
    get().applyPayload(await api.gotoRevision(project.id, revId));
    get().clearSelection();
  },
}));
