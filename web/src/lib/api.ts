export type ApiError = { detail?: string; message?: string };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers || {}),
    },
    ...init,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = (await res.json()) as ApiError;
      if (data?.detail) detail = data.detail;
      else if (data?.message) detail = data.message;
    } catch {
      try {
        const text = await res.text();
        if (text) detail = text.slice(0, 300);
      } catch {
        /* ignore */
      }
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export type AuthStatus = {
  authenticated: boolean;
  user: { id: number; email: string | null; name: string | null; picture: string | null } | null;
  google_configured: boolean;
  google_linked: boolean;
  channel: Channel | null;
  onboarding_complete: boolean;
};

export type Channel = {
  id: number;
  channel_id: string;
  title: string;
  description: string | null;
  custom_url: string | null;
  thumbnail: string | null;
  subscriber_count: number | null;
  video_count: number | null;
  view_count: number | null;
  is_selected: number;
};

export type Niche = {
  id: number;
  slug: string;
  name: string;
  description: string;
  audience: string;
  demand_score: number;
  competition_score: number;
  shorts_fit_score: number;
  repeatability_score: number;
  difficulty_score: number;
  monetization_score: number;
  evergreen_score: number;
  visual_score: number;
  total_score: number;
  rationale: string | null;
  active: number;
};

export type QueueItem = {
  id: number;
  idea_id: number;
  status: string;
  position: number;
  priority: number;
  attempts: number;
  last_error: string | null;
  timeline: { status: string; at: string; note?: string | null }[];
  topic: string;
  angle: string | null;
  title: string | null;
  quality_score: number | null;
  output_path: string | null;
  project_status: string | null;
  updated_at: string;
};

export type Idea = {
  id: number;
  topic: string;
  angle: string | null;
  hook: string | null;
  audience: string | null;
  kind: string;
  novelty_score: number | null;
  confidence_score: number | null;
  status: string;
  created_at: string;
};

export type Scene = {
  id: number;
  scene_no: number;
  narration: string;
  visual_prompt: string;
  overlay_text: string | null;
  motion: string;
  transition: string;
  duration: number;
  start_at: number;
  asset_url?: string | null;
  audio_url?: string | null;
};

export type Script = {
  id: number;
  idea_id: number;
  hook: string;
  body: string;
  cta: string;
  title: string;
  description: string;
  hashtags: string[];
  keywords: string[];
  alt_hooks: string[];
  pinned_comment: string;
  voice_direction: string;
  target_seconds: number;
  word_count: number;
  approved: number;
  scenes?: Scene[];
};

export type AutomationState = {
  status: string;
  current_queue_id: number | null;
  current_step: string | null;
  current_progress: number;
  last_error: string | null;
  paused_reason: string | null;
  next_run_at: string | null;
};

export type Schedule = {
  enabled: number;
  approval_mode: number;
  videos_per_day: number;
  publish_times: string[];
  timezone: string;
  days_of_week: number[];
  min_gap_minutes: number;
  quiet_start: string | null;
  quiet_end: string | null;
  visibility: string;
};

export type QualityReport = {
  score: number;
  threshold: number;
  checks: { name: string; score: number; weight: number; detail: string }[];
  suggestions: string[];
  width: number;
  height: number;
  duration: number;
};

export type Project = {
  id: number;
  idea_id: number;
  script_id: number | null;
  title: string;
  status: string;
  output_path: string | null;
  duration: number | null;
  quality_score: number | null;
  quality_report: QualityReport | null;
};
