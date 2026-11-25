export type TaskStatus =
  "pending" | "running" | "paused" | "completed" | "cancelled";

export interface Task {
  id: string;
  session_id: string;
  request: string;
  kind: string;
  status: TaskStatus;
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UsageRecord {
  id: number;
  model: string;
  role: string;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number;
  success: number;
}

export interface Session {
  id: string;
  created_at: string;
}

export interface ModelHealth {
  model: string;
  context_window: number | null;
  quota_remaining: number | null;
  cooldown_until: string | null;
  healthy: number;
  updated_at: string;
}

export interface Capability {
  key: string;
  capability: string;
  description: string;
  oauth_scope: string | null;
  read_only: boolean;
  configured: boolean;
}

export interface Approval {
  id: string;
  capability: string;
  parameters: Record<string, unknown>;
  status: string;
  expires_at: number;
  created_at: number;
}

export interface Action {
  id: string;
  capability: string;
  parameters: Record<string, unknown>;
  approval_id: string;
  status: string;
  provider_id: string | null;
  error_type: string | null;
  created_at: string;
}

export interface Schedule {
  id: string;
  session_id: string;
  request: string;
  recurrence: "once" | "daily";
  timezone: string;
  next_run_at: string;
  status: string;
  misfire_policy: string;
}

export interface BrowserSession {
  owner: string;
  csrf: string;
  expires_at: number;
}

export interface DashboardData {
  tasks: Task[];
  sessions: Session[];
  models: ModelHealth[];
  capabilities: Capability[];
  approvals: Approval[];
  actions: Action[];
  schedules: Schedule[];
}
