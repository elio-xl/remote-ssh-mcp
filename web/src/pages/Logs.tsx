import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronRight, RefreshCw, ScrollText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/EmptyState";
import { logsApi } from "@/api/logs";
import type { AuditEvent, EventFilter } from "@/lib/types";

const eventColors: Record<string, string> = {
  plan_created: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  approval_granted: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  approval_rejected: "bg-red-500/10 text-red-500 border-red-500/20",
  run_finished: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  run_failed: "bg-red-500/10 text-red-500 border-red-500/20",
  step_failed: "bg-red-500/10 text-red-500 border-red-500/20",
  instruction_blocked: "bg-red-500/10 text-red-500 border-red-500/20",
  plan_expired: "bg-gray-500/10 text-gray-500 border-gray-500/20",
  mcp_call_started: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
  mcp_call_finished: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  mcp_call_failed: "bg-red-500/10 text-red-500 border-red-500/20",
};

const dotColor = (event: string): string => {
  if (event.includes("failed") || event.includes("blocked")) return "bg-red-400";
  if (event.includes("finished") || event.includes("granted")) return "bg-emerald-400";
  return "bg-blue-400";
};

function timeStr(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

export function LogsPage() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<EventFilter>("");
  const [limit, setLimit] = useState(200);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await logsApi.read(limit, filter || undefined);
      setEvents(response.events.map(mapAuditEvent));
    } catch {
      // no-op
    } finally {
      setLoading(false);
    }
  }, [filter, limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const eventLabel = (eventType: string): string => {
    const key = `logs.events.${eventType}`;
    const translated = t(key);
    return translated === key ? eventType : translated;
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-[22px] font-bold tracking-tight">{t("logs.title")}</h1>
        <div className="flex gap-2">
          <Select value={filter} onValueChange={(v) => setFilter(v as EventFilter)}>
            <SelectTrigger className="h-8 w-[130px] text-[12px]">
              <SelectValue placeholder={t("logs.allEvents")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">{t("logs.allEvents")}</SelectItem>
              <SelectItem value="plan_created">{t("logs.events.plan_created")}</SelectItem>
              <SelectItem value="approval_requested">{t("logs.events.approval_requested")}</SelectItem>
              <SelectItem value="approval_granted">{t("logs.events.approval_granted")}</SelectItem>
              <SelectItem value="approval_rejected">{t("logs.events.approval_rejected")}</SelectItem>
              <SelectItem value="run_started">{t("logs.events.run_started")}</SelectItem>
              <SelectItem value="step_started">{t("logs.events.step_started")}</SelectItem>
              <SelectItem value="step_finished">{t("logs.events.step_finished")}</SelectItem>
              <SelectItem value="step_failed">{t("logs.events.step_failed")}</SelectItem>
              <SelectItem value="instruction_blocked">{t("logs.events.instruction_blocked")}</SelectItem>
              <SelectItem value="run_finished">{t("logs.events.run_finished")}</SelectItem>
              <SelectItem value="run_failed">{t("logs.events.run_failed")}</SelectItem>
              <SelectItem value="plan_expired">{t("logs.events.plan_expired")}</SelectItem>
              <SelectItem value="mcp_call_started">{t("logs.events.mcp_call_started")}</SelectItem>
              <SelectItem value="mcp_call_finished">{t("logs.events.mcp_call_finished")}</SelectItem>
              <SelectItem value="mcp_call_failed">{t("logs.events.mcp_call_failed")}</SelectItem>
            </SelectContent>
          </Select>
          <Select value={String(limit)} onValueChange={(v) => setLimit(Number(v))}>
            <SelectTrigger className="h-8 w-[100px] text-[12px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[50, 200, 1000, 5000].map((n) => (
                <SelectItem key={n} value={String(n)}>{t("logs.limit", { n })}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" size="icon" className="h-8 w-8" onClick={refresh} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <div key={i} className="h-16 animate-pulse rounded-xl bg-muted/50" />)}
        </div>
      )}

      {!loading && events.length === 0 && (
        <div className="apple-group p-8">
          <EmptyState
            icon={<ScrollText className="h-10 w-10 text-muted-foreground/30" />}
            title={t("logs.empty")}
            description={t("logs.emptyDesc")}
          />
        </div>
      )}

      <div className="space-y-2">
        {events.map((event, i) => {
          const eventKey = event.id || `${event.ts}-${i}`;
          const expanded = expandedId === eventKey;
          return (
            <div key={eventKey} className="apple-group">
              <button
                className="w-full flex items-center gap-3 px-4 py-3 text-left"
                onClick={() => setExpandedId(expanded ? null : eventKey)}
              >
                <div className={`h-2 w-2 rounded-full shrink-0 ${dotColor(event.event)}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[12px] text-muted-foreground">{timeStr(event.ts)}</span>
                    <Badge
                      variant="outline"
                      className={`text-[10px] font-medium ${eventColors[event.event] ?? "bg-muted"}`}
                    >
                      {eventLabel(event.event)}
                    </Badge>
                  </div>
                  <p className="text-[13px] truncate mt-0.5">
                    <span className="font-mono text-[11px] text-muted-foreground">{event.planId || event.stepId || event.id}</span>
                    {event.kind && <span className="mx-1.5 text-muted-foreground">·</span>}
                    {event.kind && <span className="text-[12px]">{event.kind}</span>}
                    {event.connectionName && <span className="ml-1.5 text-[12px] text-muted-foreground">{event.connectionName}</span>}
                  </p>
                </div>
                {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />}
              </button>
              {expanded && (
                <div className="border-t border-border/[0.6] px-4 py-3 space-y-3">
                  <DetailGrid event={event} t={t} />
                  {(event.stdoutExcerpt || event.stderrExcerpt) && (
                    <div className="grid gap-3 lg:grid-cols-2">
                      {event.stdoutExcerpt && <LogBlock title="stdout" text={event.stdoutExcerpt} />}
                      {event.stderrExcerpt && <LogBlock title="stderr" text={event.stderrExcerpt} />}
                    </div>
                  )}
                  <LogBlock title={t("logs.rawEvent")} text={JSON.stringify(event.raw, null, 2)} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

const fieldKeys: Record<string, string> = {
  event_id: "logs.fields.event_id",
  actor: "logs.fields.actor",
  target_alias: "logs.fields.target_alias",
  plan_id: "logs.fields.plan_id",
  run_id: "logs.fields.run_id",
  step_id: "logs.fields.step_id",
  decision: "logs.fields.decision",
  exit_code: "logs.fields.exit_code",
  elapsed_seconds: "logs.fields.elapsed_seconds",
  error_type: "logs.fields.error_type",
  stdout_digest: "logs.fields.stdout_digest",
  stderr_digest: "logs.fields.stderr_digest",
};

function DetailGrid({ event, t }: { event: AuditEvent; t: (key: string) => string }) {
  const fields = [
    ["event_id", event.id],
    ["actor", event.actor],
    ["target_alias", event.connectionName],
    ["plan_id", event.planId],
    ["run_id", event.runId],
    ["step_id", event.stepId],
    ["decision", event.decision],
    ["exit_code", event.exitCode],
    ["elapsed_seconds", event.elapsedSeconds],
    ["error_type", event.errorType],
    ["stdout_digest", event.stdoutDigest],
    ["stderr_digest", event.stderrDigest],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");

  return (
    <div className="grid gap-1.5 text-[12px] sm:grid-cols-2 lg:grid-cols-3">
      {fields.map(([label, value]) => (
        <div key={String(label)} className="min-w-0 rounded-lg bg-muted/30 px-3 py-2">
          <div className="text-muted-foreground">{t(fieldKeys[String(label)] ?? String(label))}</div>
          <div className="break-words font-mono text-[11px] mt-0.5">{String(value)}</div>
        </div>
      ))}
    </div>
  );
}

function LogBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[11px] font-medium text-muted-foreground">{title}</div>
      <pre className="max-h-80 overflow-auto rounded-lg bg-muted/30 p-3 text-[12px] leading-relaxed whitespace-pre-wrap font-mono">
        {text}
      </pre>
    </div>
  );
}

function mapAuditEvent(raw: unknown): AuditEvent {
  const event = (raw ?? {}) as {
    id?: string;
    timestamp?: number;
    event_type?: string;
    actor?: string;
    plan_id?: string;
    run_id?: string;
    step_id?: string;
    instruction_kind?: string;
    target_alias?: string;
    risk_level?: string;
    decision?: string;
    exit_code?: number;
    elapsed_seconds?: number;
    stdout_digest?: string;
    stderr_digest?: string;
    stdout_excerpt?: string;
    stderr_excerpt?: string;
    error_type?: string;
    instruction_preview?: string;
    error_message?: string;
    metadata?: Record<string, unknown>;
  };
  return {
    id: event.id ?? "",
    ts: event.timestamp ?? 0,
    event: event.event_type ?? "",
    actor: event.actor ?? "",
    planId: event.plan_id ?? "",
    runId: event.run_id ?? "",
    stepId: event.step_id ?? "",
    kind: event.instruction_kind ?? "",
    connectionName: event.target_alias ?? "",
    status: event.exit_code !== undefined ? `exit ${event.exit_code}` : "",
    risk: event.risk_level ?? "",
    decision: event.decision ?? "",
    exitCode: event.exit_code,
    elapsedSeconds: event.elapsed_seconds,
    stdoutDigest: event.stdout_digest ?? "",
    stderrDigest: event.stderr_digest ?? "",
    stdoutExcerpt: event.stdout_excerpt ?? "",
    stderrExcerpt: event.stderr_excerpt ?? "",
    errorType: event.error_type ?? "",
    summary: event.error_message || event.instruction_preview || metadataSummary(event.metadata) || "",
    raw: raw as Record<string, unknown>,
  };
}

function metadataSummary(metadata?: Record<string, unknown>) {
  if (!metadata) return "";
  const toolName = metadata.tool_name;
  if (typeof toolName === "string") return toolName;
  return "";
}
