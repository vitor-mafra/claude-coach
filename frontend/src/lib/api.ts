// Typed API client. Types are auto-generated from the FastAPI OpenAPI spec into
// ./api-generated.ts (run `make typegen` to refresh after backend changes).
// This module exposes friendly aliases + a thin fetch wrapper.

import type { components } from "./api-generated";

type Schemas = components["schemas"];

export type Health = Schemas["HealthResponse"];
export type Profile = Schemas["Profile"];
export type Exercise = Schemas["Exercise"];
export type Plan = Schemas["Plan"];
export type WorkoutTemplate = Schemas["WorkoutTemplate"];
export type ExerciseRef = Schemas["ExerciseRef"];
export type RestSpec = Schemas["RestSpec"];
export type RunSegment = Schemas["RunSegment"];
export type WarmupSuggestion = Schemas["WarmupSuggestion"];

export type MetaRepsBlock = Schemas["MetaRepsBlock"];
export type PyramidBlock = Schemas["PyramidBlock"];
export type BiSetBlock = Schemas["BiSetBlock"];
export type BiSetExercise = Schemas["BiSetExercise"];
export type DropsetBlock = Schemas["DropsetBlock"];
export type TabataBlock = Schemas["TabataBlock"];
export type IntervalRunBlock = Schemas["IntervalRunBlock"];
export type ContinuousRunBlock = Schemas["ContinuousRunBlock"];
export type FartlekBlock = Schemas["FartlekBlock"];
export type Block = WorkoutTemplate["blocks"][number];

// Domain-derived literals (generated as inline string unions on each field).
export type Weekday = NonNullable<Profile["training_days"]>[number];
export type HRZone = RunSegment["hr_zone"];
export type MuscleGroup = Exercise["primary_muscle_group"];
export type Equipment = Exercise["equipment"];
export type Sex = Profile["sex"];

// Plan.schedule maps weekday → ordered list of template_ids. Allow Partial since
// every weekday key may be omitted before the scheduler runs.
export type Schedule = NonNullable<Plan["schedule"]>;

export type LLMUsageSummary = Schemas["UsageSummary"];
export type LLMTaskUsage = Schemas["TaskUsage"];

export type WorkoutTodayResponse = Schemas["WorkoutTodayResponse"];
export type PlannedWorkout = Schemas["PlannedWorkout"];
export type PlannedExercise = Schemas["PlannedExercise"];
export type PlannedSet = Schemas["PlannedSet"];
export type SessionCreate = Schemas["SessionCreate"];
export type SetInput = Schemas["SetInput"];
export type SessionCreateResponse = Schemas["SessionCreateResponse"];
export type SessionOut = Schemas["SessionOut"];
export type SetOut = Schemas["SetOut"];
export type LinkedActivity = Schemas["LinkedActivity"];
export type OneRMRow = Schemas["OneRMRow"];
export type GarminDailyRow = Schemas["DailyMetricRow"];
export type GarminActivityRow = Schemas["ActivityRow"];
export type GarminSyncResponse = Schemas["SyncResponse"];
export type BriefingResponse = Schemas["BriefingResponse"];
export type BriefingListItem = Schemas["BriefingListItem"];
export type ReportResponse = Schemas["ReportResponse"];
export type ReportListItem = Schemas["ReportListItem"];
export type Dashboard = Schemas["DashboardResponse"];
export type TodayCard = Schemas["TodayCard"];
export type DailyTrend = Schemas["DailyTrendRow"];
export type WeeklyVolume = Schemas["WeeklyVolumeRow"];
export type RecentActivity = Schemas["RecentActivity"];
export type BodyBatteryPoint = Schemas["BodyBatteryPoint"];

class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(`/api${path}`, { credentials: "include" });
  if (!r.ok) throw new HttpError(r.status, `${path}: ${r.status}`);
  return r.json();
}

async function sendJSON<T>(path: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (!r.ok) throw new HttpError(r.status, `${method} ${path}: ${r.status}`);
  if (r.status === 204) return undefined as T;
  return r.json();
}

export { HttpError };

export const api = {
  health: () => getJSON<Health>("/health"),
  profile: {
    get: () => getJSON<Profile | null>("/profile"),
    exists: () => getJSON<{ exists: boolean }>("/profile/exists"),
    put: async (p: Profile): Promise<Profile> => {
      const r = await fetch("/api/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      if (!r.ok) throw new Error(`PUT /profile: ${r.status}`);
      return r.json();
    },
  },
  exercises: {
    list: () => getJSON<Exercise[]>("/exercises"),
    get: (id: string) => getJSON<Exercise>(`/exercises/${id}`),
  },
  plans: {
    list: () => getJSON<string[]>("/plans"),
    get: (slug: string) => getJSON<Plan>(`/plans/${slug}`),
    review: (slug: string) => getJSON<{ content: string }>(`/plans/${slug}/review`),
    regenerateSchedule: async (slug: string): Promise<Plan> => {
      const r = await fetch(`/api/plans/${slug}/schedule/regenerate`, { method: "POST" });
      if (!r.ok) throw new Error(`regenerate: ${r.status}`);
      return r.json();
    },
  },
};

export const apiWorkouts = {
  today: (date?: string) =>
    getJSON<WorkoutTodayResponse>(`/workouts/today${date ? `?date=${date}` : ""}`),
};

export const apiSessions = {
  list: (params?: { start?: string; end?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start) qs.set("start", params.start);
    if (params?.end) qs.set("end", params.end);
    if (params?.limit) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return getJSON<SessionOut[]>(`/sessions${q ? `?${q}` : ""}`);
  },
  get: (id: number) => getJSON<SessionOut>(`/sessions/${id}`),
  create: (payload: SessionCreate) =>
    sendJSON<SessionCreateResponse>("/sessions", "POST", payload),
  setActivity: (id: number, activityId: number | null) =>
    sendJSON<SessionOut>(`/sessions/${id}/activity`, "PATCH", { activity_id: activityId }),
  delete: (id: number) => sendJSON<void>(`/sessions/${id}`, "DELETE"),
  exerciseHistory: (exerciseId: string, sinceDays = 180) =>
    getJSON<OneRMRow[]>(
      `/sessions/exercises/${exerciseId}/history?since_days=${sinceDays}`,
    ),
};

export const apiGarmin = {
  sync: (date?: string) =>
    sendJSON<GarminSyncResponse>(`/garmin/sync${date ? `?date=${date}` : ""}`, "POST"),
  runs: (limit = 20) => getJSON<unknown[]>(`/garmin/runs?limit=${limit}`),
  daily: (params?: { start?: string; end?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start) qs.set("start", params.start);
    if (params?.end) qs.set("end", params.end);
    if (params?.limit) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return getJSON<GarminDailyRow[]>(`/garmin/daily${q ? `?${q}` : ""}`);
  },
  activities: (params?: { start?: string; end?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.start) qs.set("start", params.start);
    if (params?.end) qs.set("end", params.end);
    if (params?.limit) qs.set("limit", String(params.limit));
    const q = qs.toString();
    return getJSON<GarminActivityRow[]>(`/garmin/activities${q ? `?${q}` : ""}`);
  },
};

export const apiBriefing = {
  generate: (params?: { date?: string; refreshGarmin?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.date) qs.set("date", params.date);
    if (params?.refreshGarmin === false) qs.set("refresh_garmin", "false");
    const q = qs.toString();
    return sendJSON<BriefingResponse>(`/briefing/today${q ? `?${q}` : ""}`, "POST");
  },
  list: (limit = 20) => getJSON<BriefingListItem[]>(`/briefing?limit=${limit}`),
  get: (id: number) => getJSON<BriefingResponse>(`/briefing/${id}`),
};

export const apiDashboard = {
  get: () => getJSON<Dashboard>("/dashboard"),
};

export type AuthStatus = Schemas["AuthStatus"];

export const apiAuth = {
  me: () => getJSON<AuthStatus>("/auth/me"),
  login: (password: string) => sendJSON<AuthStatus>("/auth/login", "POST", { password }),
  logout: () => sendJSON<AuthStatus>("/auth/logout", "POST"),
};

export type SystemStatus = Schemas["SystemStatus"];
export type GarminConnectResponse = Schemas["GarminConnectResponse"];
export type GarminStatusResponse = Schemas["GarminStatusResponse"];
export type GarminBackfillResponse = Schemas["GarminBackfillResponse"];
export type PlanUploadResponse = Schemas["PlanUploadResponse"];

export const apiAdmin = {
  system: () => getJSON<SystemStatus>("/admin/system"),
  garminStatus: () => getJSON<GarminStatusResponse>("/admin/garmin/status"),
  garminConnect: (params?: { email?: string; password?: string; mfaCode?: string }) =>
    sendJSON<GarminConnectResponse>("/admin/garmin/connect", "POST", {
      email: params?.email ?? null,
      password: params?.password ?? null,
      mfa_code: params?.mfaCode ?? null,
    }),
  garminDisconnect: () => sendJSON<void>("/admin/garmin/tokens", "DELETE"),
  garminBackfill: (start: string, end: string) =>
    sendJSON<GarminBackfillResponse>("/admin/garmin/backfill", "POST", { start, end }),
  uploadPlan: async (file: File, slug?: string, skipSchedule = false) => {
    const fd = new FormData();
    fd.append("pdf", file);
    if (slug) fd.append("slug", slug);
    if (skipSchedule) fd.append("skip_schedule", "true");
    const r = await fetch("/api/plans/upload", {
      method: "POST",
      body: fd,
      credentials: "include",
    });
    if (!r.ok) throw new HttpError(r.status, `upload: ${r.status} ${await r.text()}`);
    return (await r.json()) as PlanUploadResponse;
  },
};

export const apiReports = {
  generate: (params?: { weekStart?: string; weekEnd?: string; sendEmail?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.weekStart) qs.set("week_start", params.weekStart);
    if (params?.weekEnd) qs.set("week_end", params.weekEnd);
    if (params?.sendEmail) qs.set("send_email", "true");
    const q = qs.toString();
    return sendJSON<ReportResponse>(`/reports/generate${q ? `?${q}` : ""}`, "POST");
  },
  list: (limit = 20) => getJSON<ReportListItem[]>(`/reports?limit=${limit}`),
  get: (id: number) => getJSON<ReportResponse>(`/reports/${id}`),
  delete: (id: number) => sendJSON<void>(`/reports/${id}`, "DELETE"),
};

export const apiLLM = {
  usage: (days = 30) => getJSON<LLMUsageSummary>(`/llm/usage?days=${days}`),
};

// Backwards-compat shim for existing imports.
export const fetchHealth = api.health;
