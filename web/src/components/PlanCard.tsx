import { useTranslation } from "react-i18next";
import { Calendar, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { ExecutionPlan } from "@/lib/types";

const statusVariant: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  draft: "secondary",
  pending_approval: "secondary",
  approved: "default",
  executed: "default",
  rejected: "destructive",
  expired: "outline",
};

const riskVariant: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  low: "outline",
  medium: "secondary",
  high: "destructive",
};

function timeStr(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

interface PlanCardProps {
  plan: ExecutionPlan;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onExecute: (id: string) => void;
  onView: (plan: ExecutionPlan) => void;
}

export function PlanCard({ plan, onApprove, onReject, onExecute, onView }: PlanCardProps) {
  const { t } = useTranslation();
  const isDraft = plan.status === "draft" || plan.status === "pending_approval";
  const isApproved = plan.status === "approved";

  const statusLabel = (status: string): string => {
    switch (status) {
      case "draft":
      case "pending_approval": return t("plans.pending");
      case "approved": return t("plans.approved");
      case "executed": return t("plans.executed");
      case "rejected": return t("plans.rejected");
      case "expired": return t("plans.expired");
      default: return status;
    }
  };

  return (
    <div className="apple-group">
      <div className="flex items-center gap-4 px-4 py-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-mono text-[11px] text-muted-foreground truncate">{plan.planId}</span>
            <Badge variant={statusVariant[plan.status] ?? "outline"} className="text-[10px] shrink-0">
              {statusLabel(plan.status)}
            </Badge>
            <Badge variant={riskVariant[plan.risk] ?? "outline"} className="text-[10px] capitalize shrink-0">
              {t("plans.risk", { level: plan.risk })}
            </Badge>
          </div>
          <p className="text-[13px] font-medium truncate">
            <span className="text-muted-foreground">{plan.connectionName}</span>
            <span className="mx-1.5 text-muted-foreground/40">·</span>
            <span>{plan.summary}</span>
          </p>
          <div className="flex items-center gap-1.5 mt-1 text-[11px] text-muted-foreground">
            <Calendar className="h-3 w-3" />
            <span>{t("plans.expires")}: {timeStr(plan.expiresAt)}</span>
            {plan.approvalNote && (
              <span className="truncate ml-2">— {plan.approvalNote}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Button variant="ghost" size="sm" className="h-7 text-[12px]" onClick={() => onView(plan)}>
            {t("plans.viewDetail")}
            <ChevronRight className="ml-1 h-3 w-3" />
          </Button>
          {isDraft && (
            <>
              <Button size="sm" className="h-7 text-[12px] px-3" onClick={() => onApprove(plan.planId)}>
                {t("plans.approve")}
              </Button>
              <Button size="sm" variant="destructive" className="h-7 text-[12px] px-3" onClick={() => onReject(plan.planId)}>
                {t("plans.reject")}
              </Button>
            </>
          )}
          {isApproved && (
            <Button size="sm" className="h-7 text-[12px] px-3" onClick={() => onExecute(plan.planId)}>
              {t("plans.execute")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
