// Mirror of the backend pydantic contracts (backend/aicut/models.py).
// Kept hand-synced; the shapes are small and stable.

export type Aspect = "source" | "9:16" | "1:1";
export type CaptionGranularity = "segment" | "word";
export type TranscriptStatus = "pending" | "running" | "ready" | "error";

export interface Word {
  w: string;
  start: number;
  end: number;
  prob?: number | null;
}

export interface Segment {
  id: number;
  start: number;
  end: number;
  text: string;
  words: Word[];
}

export interface Transcript {
  source: string;
  duration: number;
  language: string;
  segments: Segment[];
}

export interface CaptionSettings {
  enabled: boolean;
  granularity: CaptionGranularity;
  font: string;
  font_size: number;
  max_lines: number;
}

export type Span = [number, number];

export interface CompiledEDL {
  keep: Span[];
  captions: CaptionSettings;
  aspect: Aspect;
  duration: number;
}

export interface Revision {
  id: string;
  label: string;
  notes: string;
  edl: CompiledEDL;
  created_at: number;
}

export interface ExportPresetSettings {
  aspect: Aspect | null;
  captions: boolean | null;
  granularity: CaptionGranularity;
  quality: string;
}

export interface ProjectSettings {
  captions: CaptionSettings;
  aspect: Aspect;
  export_preset?: ExportPresetSettings | null;
}

export interface Project {
  id: string;
  name: string;
  source_path: string;
  media_url: string;
  thumbnail: string | null;
  duration: number;
  transcript_status: TranscriptStatus;
  transcript_error: string | null;
  transcript_progress: number;
  language: string | null;
  settings: ProjectSettings;
  revisions: Revision[];
  head_revision_id: string | null;
  created_at: number;
}

export interface WordRef {
  segment_id: number;
  word_index_start: number;
  word_index_end: number;
}

export interface CommandResult {
  ok: boolean;
  revision?: Revision;
  summary?: string;
  notes?: string;
  error?: string;
}

export interface Workspace {
  id: string;
  name: string;
  clip_ids: string[];
  created_at: number;
}
