export interface ExecutionPlan {
  planId: string;
  kind: string;
  connectionName: string;
  status: "draft" | "pending_approval" | "approved" | "executed" | "rejected" | "expired";
  approvalRequired: boolean;
  risk: "low" | "medium" | "high";
  operationalRisk: string;
  approvalSummary: Record<string, string>;
  summary: string;
  rollbackPlan: string;
  createdAt: number;
  expiresAt: number;
  payload: Record<string, unknown>;
  verification?: string;
  approvedAt?: number;
  executedAt?: number;
  approvalNote?: string;
}

export interface AuditEvent {
  id: string;
  ts: number;
  event: string;
  actor: string;
  planId: string;
  runId: string;
  stepId: string;
  kind: string;
  connectionName: string;
  status: string;
  risk: string;
  decision: string;
  exitCode?: number;
  elapsedSeconds?: number;
  stdoutDigest: string;
  stderrDigest: string;
  stdoutExcerpt: string;
  stderrExcerpt: string;
  errorType: string;
  summary: string;
  raw: Record<string, unknown>;
}

export type SSHAuthType = "password" | "key";

export interface SSHConfigCrudEntry {
  host: string;
  hostname: string;
  user: string;
  port: number;
  type: SSHAuthType;
  IdentityFile: string;
  password: string;
  workdir: string;
  remarks: string;
}

export interface SSHConfigEntry {
  host: string;
  hostname?: string;
  user?: string;
  port?: number;
  identityFile?: string[];
  proxyJump?: string;
  forwardAgent?: boolean;
  serverAliveInterval?: number;
  serverAliveCountMax?: number;
  strictHostKeyChecking?: string;
  userKnownHostsFile?: string;
  logLevel?: string;
  compression?: boolean;
  requestTty?: string;
  remoteCommand?: string;
  localForward?: string[];
  remoteForward?: string[];
  extraDirectives?: Record<string, string | null>;
  comment?: string;
  sourceFile?: string;
  lineNumber?: number;
}

export interface SSHConfigSummary {
  host: string;
  hostname?: string;
  user: string;
  port: number;
  keyCount: number;
  hasProxyJump: boolean;
  comment?: string;
  lineNumber: number;
}

export interface HealthStatus {
  status: string;
  lastUsed?: string;
  uptime?: string;
}

export type EventFilter = "plan_created" | "approval_requested" | "approval_granted" | "approval_rejected" | "plan_expired" | "run_started" | "step_started" | "step_finished" | "step_failed" | "instruction_blocked" | "run_finished" | "run_failed" | "mcp_call_started" | "mcp_call_finished" | "mcp_call_failed" | "";
export type PlanFilter = "all" | "draft" | "pending_approval" | "approved" | "executed" | "rejected" | "expired";
