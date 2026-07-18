// REST + SSE client. Same-origin in dev via the Vite proxy (/api, /media).

import type { CommandResult, Project, Transcript } from "./types";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.error || detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export interface ProjectPayload {
  project: Project;
  transcript: Transcript | null;
}

export const api = {
  async listProjects(): Promise<Project[]> {
    const r = await fetch("/api/projects");
    return (await jsonOrThrow<{ projects: Project[] }>(r)).projects;
  },

  async getProject(id: string): Promise<ProjectPayload> {
    const r = await fetch(`/api/projects/${id}`);
    return jsonOrThrow<ProjectPayload>(r);
  },

  async createProject(path: string, name?: string): Promise<Project> {
    const r = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, name }),
    });
    return (await jsonOrThrow<{ project: Project }>(r)).project;
  },

  async uploadProject(file: File): Promise<Project> {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch("/api/projects/upload", { method: "POST", body: form });
    return (await jsonOrThrow<{ project: Project }>(r)).project;
  },

  async deleteProject(id: string): Promise<void> {
    await fetch(`/api/projects/${id}`, { method: "DELETE" });
  },

  async command(id: string, instruction: string): Promise<CommandResult> {
    const r = await fetch(`/api/projects/${id}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    });
    return jsonOrThrow<CommandResult>(r);
  },

  async edit(id: string, action: unknown, notes?: string): Promise<ProjectPayload> {
    const r = await fetch(`/api/projects/${id}/edits`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, notes }),
    });
    return jsonOrThrow<ProjectPayload>(r);
  },

  async oneClick(id: string, kind: string): Promise<ProjectPayload> {
    const r = await fetch(`/api/projects/${id}/actions/${kind}`, { method: "POST" });
    return jsonOrThrow<ProjectPayload>(r);
  },

  async undo(id: string): Promise<ProjectPayload> {
    const r = await fetch(`/api/projects/${id}/undo`, { method: "POST" });
    return jsonOrThrow<ProjectPayload>(r);
  },

  async redo(id: string): Promise<ProjectPayload> {
    const r = await fetch(`/api/projects/${id}/redo`, { method: "POST" });
    return jsonOrThrow<ProjectPayload>(r);
  },

  async gotoRevision(id: string, revId: string): Promise<ProjectPayload> {
    const r = await fetch(`/api/projects/${id}/revisions/${revId}`, { method: "POST" });
    return jsonOrThrow<ProjectPayload>(r);
  },

  async export(id: string, preset: unknown): Promise<{ job_id: string }> {
    const r = await fetch(`/api/projects/${id}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(preset),
    });
    return jsonOrThrow<{ job_id: string }>(r);
  },

  async listExports(id: string): Promise<{ exports: { name: string; url: string; size: number }[] }> {
    const r = await fetch(`/api/projects/${id}/exports`);
    return jsonOrThrow(r);
  },

  // SSE subscription; returns an unsubscribe fn.
  events(id: string, onEvent: (e: MessageEvent, type: string) => void): () => void {
    const es = new EventSource(`/api/projects/${id}/events`);
    const types = ["transcription", "export", "plan", "message"];
    for (const t of types) es.addEventListener(t, (e) => onEvent(e as MessageEvent, t));
    es.onerror = () => {
      /* EventSource auto-reconnects; nothing to do */
    };
    return () => es.close();
  },
};
