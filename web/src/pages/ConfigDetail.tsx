import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, FileEdit, Trash2, Wifi, Key, Folder, User, Hash, Globe, Shield, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { configApi } from "@/api/config";
import type { SSHAuthType, SSHConfigCrudEntry } from "@/lib/types";

const emptyForm: SSHConfigCrudEntry = {
  host: "",
  hostname: "",
  user: "root",
  port: 22,
  type: "password",
  IdentityFile: "",
  password: "",
  workdir: "",
  remarks: "",
};

type FormErrors = Partial<Record<keyof SSHConfigCrudEntry, string>>;

function normalizeForm(form: SSHConfigCrudEntry): SSHConfigCrudEntry {
  return {
    ...form,
    host: form.host.trim(),
    hostname: form.hostname.trim(),
    user: form.user.trim(),
    port: Number(form.port),
    IdentityFile: form.IdentityFile.trim(),
    password: form.password.trim(),
    workdir: form.workdir.trim(),
    remarks: form.remarks.trim(),
  };
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-xs text-destructive mt-1">{message}</p>;
}

function InfoCard({ icon: Icon, label, value, mono }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string | number; mono?: boolean }) {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-card border border-border/50 p-4">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
        <p className={`mt-1 text-[13px] font-medium truncate ${mono ? "font-mono text-[12px]" : ""}`}>{value || "—"}</p>
      </div>
    </div>
  );
}

function ConfigFormFields({
  form,
  errors,
  onChange,
  testing,
  submitting,
  onTest,
  t,
}: {
  form: SSHConfigCrudEntry;
  errors: FormErrors;
  onChange: (f: SSHConfigCrudEntry) => void;
  testing: boolean;
  submitting: boolean;
  onTest: () => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const setField = <K extends keyof SSHConfigCrudEntry>(key: K, value: SSHConfigCrudEntry[K]) => {
    onChange({ ...form, [key]: value });
  };

  return (
    <div className="space-y-4">
      <div className="apple-group">
        <div className="grid grid-cols-2 gap-4 p-4">
          <div className="space-y-1.5">
            <Label className="text-[13px] font-medium">{t("config.host")} *</Label>
            <Input className="h-9 text-[13px]" placeholder="dev-server" value={form.host} onChange={(e) => setField("host", e.target.value)} />
            <FieldError message={errors.host} />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[13px] font-medium">{t("config.hostname")} *</Label>
            <Input className="h-9 text-[13px]" placeholder="192.168.1.100" value={form.hostname} onChange={(e) => setField("hostname", e.target.value)} />
            <FieldError message={errors.hostname} />
          </div>
        </div>
        <Separator />
        <div className="grid grid-cols-2 gap-4 p-4">
          <div className="space-y-1.5">
            <Label className="text-[13px] font-medium">{t("config.user")} *</Label>
            <Input className="h-9 text-[13px]" value={form.user} onChange={(e) => setField("user", e.target.value)} />
            <FieldError message={errors.user} />
          </div>
          <div className="space-y-1.5">
            <Label className="text-[13px] font-medium">{t("config.port")} *</Label>
            <Input className="h-9 text-[13px]" type="number" min={1} max={65535} value={form.port} onChange={(e) => setField("port", Number(e.target.value))} />
            <FieldError message={errors.port} />
          </div>
        </div>
        <Separator />
        <div className="p-4 space-y-1.5">
          <Label className="text-[13px] font-medium">{t("config.type")} *</Label>
          <select
            className="h-9 w-full rounded-lg border border-input bg-transparent px-3 text-[13px] outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            value={form.type}
            onChange={(e) => {
              const authType = e.target.value as SSHAuthType;
              onChange({ ...form, type: authType, password: "", IdentityFile: "" });
            }}
          >
            <option value="password">{t("config.passwordType")}</option>
            <option value="key">{t("config.keyType")}</option>
          </select>
          <FieldError message={errors.type} />
        </div>
        <Separator />
        <div className="p-4">
          {form.type === "key" ? (
            <div className="space-y-1.5">
              <Label className="text-[13px] font-medium">{t("config.identityFile")} *</Label>
              <Input className="h-9 text-[13px]" placeholder="~/.ssh/id_rsa" value={form.IdentityFile} onChange={(e) => setField("IdentityFile", e.target.value)} />
              <FieldError message={errors.IdentityFile} />
            </div>
          ) : (
            <div className="space-y-1.5">
              <Label className="text-[13px] font-medium">{t("config.password")}（{t("config.passwordHint")}）</Label>
              <Input className="h-9 text-[13px]" type="password" placeholder={t("config.passwordHint")} value={form.password} onChange={(e) => setField("password", e.target.value)} />
              <FieldError message={errors.password} />
            </div>
          )}
        </div>
        <Separator />
        <div className="p-4 space-y-1.5">
          <Label className="text-[13px] font-medium">{t("config.workdir")}</Label>
          <Input className="h-9 text-[13px]" placeholder="/var/www/app" value={form.workdir} onChange={(e) => setField("workdir", e.target.value)} />
        </div>
        <Separator />
        <div className="p-4 space-y-1.5">
          <Label className="text-[13px] font-medium">{t("config.remarks")}</Label>
          <Textarea className="text-[13px] min-h-[60px]" placeholder={t("config.remarksPlaceholder")} value={form.remarks} onChange={(e) => setField("remarks", e.target.value)} />
        </div>
      </div>
      <div className="apple-group p-4">
        <Button variant="outline" className="w-full h-9 text-[13px]" onClick={onTest} disabled={testing || submitting}>
          {testing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Wifi className="mr-2 h-4 w-4" />}
          {testing ? t("common.testing") : t("common.test")}
        </Button>
      </div>
    </div>
  );
}

export function ConfigDetailPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { host } = useParams<{ host: string }>();

  const [entry, setEntry] = useState<SSHConfigCrudEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [editForm, setEditForm] = useState<SSHConfigCrudEntry>(emptyForm);
  const [editErrors, setEditErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);

  const loadEntry = useCallback(async () => {
    if (!host) return;
    setLoading(true);
    try {
      const detail = await configApi.get(decodeURIComponent(host));
      setEntry(detail);
    } catch (e: unknown) {
      toast.error(`${t("config.detailLoadFailed")}: ${e instanceof Error ? e.message : ""}`);
      navigate("/config", { replace: true });
    } finally {
      setLoading(false);
    }
  }, [host, navigate, t]);

  useEffect(() => { loadEntry(); }, [loadEntry]);

  const validateForm = (form: SSHConfigCrudEntry, opts: { requirePassword?: boolean } = {}): FormErrors => {
    const value = normalizeForm(form);
    const errors: FormErrors = {};
    if (!value.host) errors.host = t("config.validation.hostRequired");
    if (!value.hostname) errors.hostname = t("config.validation.hostnameRequired");
    if (!value.user) errors.user = t("config.validation.userRequired");
    if (!Number.isInteger(value.port) || value.port < 1 || value.port > 65535) errors.port = t("config.validation.portRange");
    if (value.type !== "password" && value.type !== "key") errors.type = t("config.validation.typeRequired");
    if (opts.requirePassword && value.type === "password" && !value.password) errors.password = t("config.validation.passwordRequired");
    if (value.type === "key" && !value.IdentityFile) errors.IdentityFile = t("config.validation.keyRequired");
    return errors;
  };

  const firstError = (errors: FormErrors): string | undefined => Object.values(errors).find(Boolean);

  const openEditDialog = () => {
    if (!entry) return;
    setEditForm({ ...emptyForm, ...entry, password: "" });
    setEditErrors({});
    setEditOpen(true);
  };

  const submitEdit = async () => {
    if (!entry) return;
    const errors = validateForm(editForm);
    setEditErrors(errors);
    const msg = firstError(errors);
    if (msg) { toast.error(msg); return; }
    setSubmitting(true);
    try {
      const updated = await configApi.update(entry.host, normalizeForm(editForm));
      toast.success(t("config.updateSuccess", { host: updated.host }));
      setEditOpen(false);
      setEntry(updated);
      if (updated.host !== entry.host) {
        navigate(`/config/${encodeURIComponent(updated.host)}`, { replace: true });
      }
    } catch (e: unknown) {
      toast.error(`${t("config.updateFailed")}: ${e instanceof Error ? e.message : ""}`);
    } finally {
      setSubmitting(false);
    }
  };

  const testForm = async (form: SSHConfigCrudEntry, setErrors: (e: FormErrors) => void) => {
    const errors = validateForm(form, { requirePassword: true });
    setErrors(errors);
    const msg = firstError(errors);
    if (msg) { toast.error(msg); return; }
    setTesting(true);
    try {
      const result = await configApi.test(normalizeForm(form));
      toast.success(result.message || t("config.testSuccess"));
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t("config.testFailed"));
    } finally {
      setTesting(false);
    }
  };

  const handleDelete = async () => {
    if (!entry) return;
    try {
      await configApi.delete(entry.host);
      toast.success(t("config.deleteSuccess", { host: entry.host }));
      navigate("/config", { replace: true });
    } catch (e: unknown) {
      toast.error(`${t("config.deleteFailed")}: ${e instanceof Error ? e.message : ""}`);
    } finally {
      setDeleteOpen(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-20 animate-pulse rounded bg-muted/50" />
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => <div key={i} className="h-10 animate-pulse rounded-xl bg-muted/50" />)}
        </div>
      </div>
    );
  }

  if (!entry) return null;

  const decodedHost = host ? decodeURIComponent(host) : entry.host;

  return (
    <div className="space-y-6">
      {/* Back button */}
      <button
        onClick={() => navigate("/config")}
        className="inline-flex items-center gap-1.5 text-[13px] font-medium text-primary hover:text-primary/80 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("config.title")}
      </button>

      {/* Hero card — connection identity */}
      <div className="relative overflow-hidden rounded-2xl bg-card border border-border/50 p-6">
        <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full -translate-y-1/2 translate-x-1/2" />
        <div className="relative flex items-start justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5 mb-2">
              <h1 className="text-xl font-bold tracking-tight truncate">{decodedHost}</h1>
              <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary">
                {entry.type === "key" ? <Key className="h-3 w-3" /> : <Shield className="h-3 w-3" />}
                {entry.type === "key" ? t("config.keyType") : t("config.passwordType")}
              </span>
            </div>
            <p className="text-[14px] text-muted-foreground font-mono">
              {entry.user}@{entry.hostname || "?"}:{entry.port}
            </p>
            {entry.remarks && (
              <p className="mt-2 text-[13px] text-muted-foreground/70">{entry.remarks}</p>
            )}
          </div>
          <div className="flex gap-2 shrink-0 ml-4">
            <Button variant="outline" size="sm" className="h-8 text-[13px]" onClick={openEditDialog}>
              <FileEdit className="mr-1.5 h-3.5 w-3.5" />{t("common.edit")}
            </Button>
            <Button variant="outline" size="sm" className="h-8 text-[13px] text-destructive" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />{t("common.delete")}
            </Button>
          </div>
        </div>
      </div>

      {/* Connection details */}
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground px-1">Connection</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <InfoCard icon={Globe} label={t("config.hostname")} value={entry.hostname} mono />
        <InfoCard icon={User} label={t("config.user")} value={entry.user} />
        <InfoCard icon={Hash} label={t("config.port")} value={entry.port} mono />
        <InfoCard icon={Shield} label={t("config.type")} value={entry.type === "key" ? t("config.keyType") : t("config.passwordType")} />
      </div>

      {/* Auth details */}
      {entry.type === "key" ? (
        <>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground px-1">Authentication</h3>
          <div className="grid gap-3 sm:grid-cols-1">
            <InfoCard icon={Key} label={t("config.identityFile")} value={entry.IdentityFile} mono />
          </div>
        </>
      ) : (
        <>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground px-1">Authentication</h3>
          <div className="grid gap-3 sm:grid-cols-1">
            <InfoCard icon={Key} label={t("config.password")} value={entry.password ? "******" : "—"} mono />
          </div>
        </>
      )}

      {/* Path & notes */}
      {(entry.workdir || entry.remarks) && (
        <>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground px-1">More</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {entry.workdir && <InfoCard icon={Folder} label={t("config.workdir")} value={entry.workdir} mono />}
            {entry.remarks && <InfoCard icon={FileText} label={t("config.remarks")} value={entry.remarks} />}
          </div>
        </>
      )}

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={(o) => { setEditOpen(o); if (!o) setEditErrors({}); }}>
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle className="text-[17px]">{t("config.editTitle", { host: entry.host })}</DialogTitle>
            <DialogDescription className="text-[13px]">{t("config.editDesc")}</DialogDescription>
          </DialogHeader>
          <ConfigFormFields
            form={editForm}
            errors={editErrors}
            onChange={setEditForm}
            testing={testing}
            submitting={submitting}
            onTest={() => testForm(editForm, setEditErrors)}
            t={t}
          />
          <DialogFooter className="mt-2">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(false)}>{t("common.cancel")}</Button>
            <Button size="sm" onClick={submitEdit} disabled={submitting || testing}>
              {submitting ? t("common.saving") : t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete dialog */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="text-[17px]">{t("config.deleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription className="text-[13px]">
              {t("config.deleteDesc", { host: entry.host })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction className="bg-destructive" onClick={handleDelete}>
              {t("config.deleteConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
