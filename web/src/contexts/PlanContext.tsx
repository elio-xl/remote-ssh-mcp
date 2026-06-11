import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { toast } from "sonner";
import i18n from "@/i18n";
import { plansApi } from "@/api/plans";
import type { ExecutionPlan } from "@/lib/types";

interface PlanContextType {
  plans: ExecutionPlan[];
  loading: boolean;
  refresh: () => Promise<void>;
  approve: (planId: string, note?: string) => Promise<void>;
  reject: (planId: string, reason?: string) => Promise<void>;
  execute: (planId: string) => Promise<void>;
}

interface RemotePlan {
  id?: string;
  target_alias?: string;
  goal?: string;
  summary?: string;
  risk_level?: ExecutionPlan["risk"];
  status?: ExecutionPlan["status"];
  requires_approval?: boolean;
  created_at?: number;
  expires_at?: number;
  approved_at?: number;
  executed_at?: number;
  metadata?: Record<string, unknown>;
  steps?: unknown[];
  plan_hash?: string;
}

const PlanContext = createContext<PlanContextType | null>(null);

export function PlanProvider({ children }: { children: ReactNode }) {
  const [plans, setPlans] = useState<ExecutionPlan[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await plansApi.list();
      setPlans(response.plans.map(mapRemotePlan));
    } catch {
      // keep existing
    } finally {
      setLoading(false);
    }
  }, []);

  const approve = useCallback(async (planId: string, note?: string) => {
    try {
      await plansApi.approve(planId, note);
      setPlans((prev) => prev.map((p) => (p.planId === planId ? { ...p, status: "approved" as const } : p)));
      toast.success(i18n.t("plans.approveSuccess", { id: planId }));
    } catch (e: unknown) {
      toast.error(`${i18n.t("plans.operationFailed")}: ${e instanceof Error ? e.message : ""}`);
    }
  }, []);

  const reject = useCallback(async (planId: string, reason?: string) => {
    try {
      await plansApi.reject(planId, reason);
      setPlans((prev) => prev.map((p) => (p.planId === planId ? { ...p, status: "rejected" as const } : p)));
      toast.success(i18n.t("plans.rejectSuccess", { id: planId }));
    } catch (e: unknown) {
      toast.error(`${i18n.t("plans.operationFailed")}: ${e instanceof Error ? e.message : ""}`);
    }
  }, []);

  const execute = useCallback(async (planId: string) => {
    try {
      await plansApi.execute(planId);
      setPlans((prev) => prev.map((p) => (p.planId === planId ? { ...p, status: "executed" as const } : p)));
      toast.success(i18n.t("plans.executeSuccess", { id: planId }));
    } catch (e: unknown) {
      toast.error(`${i18n.t("plans.operationFailed")}: ${e instanceof Error ? e.message : ""}`);
    }
  }, []);

  return (
    <PlanContext.Provider value={{ plans, loading, refresh, approve, reject, execute }}>
      {children}
    </PlanContext.Provider>
  );
}

export function usePlans() {
  const ctx = useContext(PlanContext);
  if (!ctx) throw new Error("usePlans must be used within PlanProvider");
  return ctx;
}

function mapRemotePlan(raw: unknown): ExecutionPlan {
  const plan = (raw ?? {}) as RemotePlan;
  const metadata = plan.metadata ?? {};
  return {
    planId: plan.id ?? "",
    kind: "remote_plan",
    connectionName: plan.target_alias ?? "",
    status: plan.status ?? "draft",
    approvalRequired: Boolean(plan.requires_approval),
    risk: plan.risk_level ?? "low",
    operationalRisk: plan.risk_level ?? "low",
    approvalSummary: {},
    summary: plan.summary || plan.goal || "remote operation",
    rollbackPlan: collectRollback(plan.steps),
    createdAt: plan.created_at ?? 0,
    expiresAt: plan.expires_at ?? 0,
    payload: { steps: plan.steps ?? [], plan_hash: plan.plan_hash },
    verification: undefined,
    approvedAt: plan.approved_at,
    executedAt: plan.executed_at,
    approvalNote: typeof metadata.approval_comment === "string" ? metadata.approval_comment : undefined,
  };
}

function collectRollback(steps: unknown[] | undefined): string {
  if (!steps?.length) return "";
  const hints = steps
    .map((step) => (step as { rollback_hint?: unknown }).rollback_hint)
    .filter((hint): hint is string => typeof hint === "string" && hint.length > 0);
  return hints.join("; ");
}
