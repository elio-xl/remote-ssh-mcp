import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { ExecutionPlan } from "@/lib/types";

function timeStr(ts: number) {
  return new Date(ts * 1000).toLocaleString();
}

interface PlanDetailDialogProps {
  plan: ExecutionPlan | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <span className="text-[13px] font-medium max-w-[60%] text-right">{value || "—"}</span>
    </div>
  );
}

export function PlanDetailDialog({ plan, open, onOpenChange }: PlanDetailDialogProps) {
  const { t } = useTranslation();
  if (!plan) return null;

  const riskLabel = (() => {
    const r = plan.risk;
    if (r === "low") return "Low";
    if (r === "medium") return "Medium";
    if (r === "high") return "High";
    return r;
  })();

  const statusLabel = (() => {
    switch (plan.status) {
      case "draft":
      case "pending_approval": return t("plans.pending");
      case "approved": return t("plans.approved");
      case "executed": return t("plans.executed");
      case "rejected": return t("plans.rejected");
      case "expired": return t("plans.expired");
      default: return plan.status;
    }
  })();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="text-[17px]">{t("plans.detail.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline" className="text-[10px]">{plan.kind}</Badge>
            <Badge variant="outline" className="text-[10px]">{t("plans.risk", { level: riskLabel })}</Badge>
            <Badge variant="outline" className="text-[10px]">{statusLabel}</Badge>
            {plan.operationalRisk && (
              <Badge variant="outline" className="text-[10px]">{plan.operationalRisk}</Badge>
            )}
          </div>

          <div className="apple-group">
            <DetailItem label={t("plans.detail.planId")} value={plan.planId} />
            <Separator />
            <DetailItem label={t("plans.detail.target")} value={plan.connectionName} />
            <Separator />
            <DetailItem label={t("plans.detail.summary")} value={plan.summary} />
            <Separator />
            <DetailItem label={t("plans.detail.status")} value={statusLabel} />
            <Separator />
            <DetailItem label={t("plans.detail.risk")} value={t("plans.risk", { level: riskLabel })} />
            {plan.rollbackPlan && (
              <>
                <Separator />
                <DetailItem label="Rollback" value={plan.rollbackPlan} />
              </>
            )}
            {plan.approvalNote && (
              <>
                <Separator />
                <DetailItem label={t("plans.detail.approverNote")} value={plan.approvalNote} />
              </>
            )}
            {plan.verification && (
              <>
                <Separator />
                <DetailItem label="Verification" value={plan.verification} />
              </>
            )}
          </div>

          <div className="text-[11px] text-muted-foreground flex flex-wrap gap-x-3 gap-y-1">
            <span>{t("plans.expires")}: {timeStr(plan.expiresAt)}</span>
            {plan.createdAt && <span>Created: {timeStr(plan.createdAt)}</span>}
            {plan.approvedAt && <span>{t("plans.approved")}: {timeStr(plan.approvedAt)}</span>}
            {plan.executedAt && <span>{t("plans.executed")}: {timeStr(plan.executedAt)}</span>}
          </div>

          {plan.payload && Object.keys(plan.payload).length > 0 && (
            <div>
              <span className="text-[12px] font-medium text-muted-foreground">{t("plans.detail.steps")}</span>
              <pre className="mt-1.5 rounded-lg bg-muted/30 p-3 text-[12px] overflow-x-auto leading-relaxed">
                {JSON.stringify(plan.payload, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
