import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Shield } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PlanCard } from "@/components/PlanCard";
import { PlanDetailDialog } from "@/components/PlanDetailDialog";
import { usePlans } from "@/contexts/PlanContext";
import type { ExecutionPlan, PlanFilter } from "@/lib/types";

type TabKey = "pending_approval" | "approved" | "executed" | "rejected";

const tabs: { key: TabKey; labelKey: string }[] = [
  { key: "pending_approval", labelKey: "plans.pending" },
  { key: "approved", labelKey: "plans.approved" },
  { key: "executed", labelKey: "plans.executed" },
  { key: "rejected", labelKey: "plans.rejected" },
];

export function PlansPage() {
  const { t } = useTranslation();
  const { plans, loading, refresh, approve, reject, execute } = usePlans();
  const [activeTab, setActiveTab] = useState<TabKey>("pending_approval");
  const [detailPlan, setDetailPlan] = useState<ExecutionPlan | null>(null);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const filtered = plans.filter((p) => p.status === activeTab);

  return (
    <div className="space-y-6">
      <h1 className="text-[22px] font-bold tracking-tight">{t("plans.title")}</h1>

      <div className="apple-group">
        <div className="flex overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex-1 px-4 py-2.5 text-[13px] font-medium text-center transition-colors border-b-2 whitespace-nowrap ${
                activeTab === tab.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(tab.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-muted/50" />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="apple-group p-8">
          <EmptyState
            icon={<Shield className="h-10 w-10 text-muted-foreground/30" />}
            title={t("plans.empty")}
            description={t("plans.emptyDesc")}
          />
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((plan) => (
            <PlanCard
              key={plan.planId}
              plan={plan}
              onApprove={approve}
              onReject={reject}
              onExecute={execute}
              onView={setDetailPlan}
            />
          ))}
        </div>
      )}

      <PlanDetailDialog
        plan={detailPlan}
        open={detailPlan !== null}
        onOpenChange={(open) => { if (!open) setDetailPlan(null); }}
      />
    </div>
  );
}
