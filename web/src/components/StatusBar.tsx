import { useTranslation } from "react-i18next";

export function StatusBar() {
  const { t } = useTranslation();

  return (
    <footer className="flex h-7 items-center justify-between border-t border-border/40 bg-card/50 px-4 text-[11px] text-muted-foreground shrink-0 backdrop-blur-lg">
      <div className="flex items-center gap-4">
        <span className="truncate">{t("status.active", { count: 0 })}</span>
      </div>
    </footer>
  );
}
