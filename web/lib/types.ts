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

export interface SessionMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface MemoryRecord {
  id: string;
  category: string;
  content: string;
  provenance: string;
  created_at: string;
  expires_at: string | null;
}

export interface SkillVersion {
  id: string;
  name: string;
  version: number;
  kind: string;
  status: string;
  procedure: string;
  permissions: string;
  evaluation: string | null;
  content: string;
  created_at: string;
}

export interface SkillMetric {
  id: string;
  task_count: number;
  success_count: number;
  model_calls: number;
  corrections: number;
}

export interface UsageSummary {
  model: string;
  calls: number;
  successful_calls: number;
  input_tokens: number | null;
  output_tokens: number | null;
  average_latency_ms: number | null;
  last_used_at: string;
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
  auth_method: "oauth" | "environment" | null;
  last_success_at: string | null;
}

export interface AccessGrant {
  capability: string;
  operation: "read" | "write";
}

export interface FilesystemRoot {
  path: string;
  operation: "read" | "write";
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
  grants: AccessGrant[];
  roots: FilesystemRoot[];
  approvals: Approval[];
  actions: Action[];
  schedules: Schedule[];
  memories: MemoryRecord[];
  skills: SkillVersion[];
  skillMetrics: SkillMetric[];
  usage: UsageSummary[];
}
