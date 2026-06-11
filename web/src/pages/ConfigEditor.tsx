import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { FileEdit, FolderOpen, Plus, Search, Wifi, ChevronRight, Loader2 } from "lucide-react";
import { open } from "@tauri-apps/plugin-dialog";
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
import { EmptyState } from "@/components/EmptyState";
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

function IdentityFilePicker({
  value,
  error,
  onChange,
}: {
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();

  const handleSelectFile = async () => {
    try {
      const selected = await open({
        multiple: false,
        directory: false,
        defaultPath: value || undefined,
        title: t("config.selectKeyFileTitle"),
      });
      if (typeof selected === "string") onChange(selected);
    } catch (e: unknown) {
      toast.error(`${t("config.filePickerFailed")}: ${e instanceof Error ? e.message : ""}`);
    }
  };

  return (
    <div className="space-y-1.5">
      <Label className="text-[13px] font-medium">{t("config.identityFile")} *</Label>
      <div className="flex gap-2">
        <Input
          placeholder="~/.ssh/id_rsa"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 text-[13px]"
        />
        <Button type="button" variant="outline" size="sm" className="h-9 shrink-0" onClick={handleSelectFile}>
          <FolderOpen className="mr-1.5 h-3.5 w-3.5" />{t("config.selectKeyFile")}
        </Button>
      </div>
      <FieldError message={error} />
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
}: {
  form: SSHConfigCrudEntry;
  errors: FormErrors;
  onChange: (form: SSHConfigCrudEntry) => void;
  testing: boolean;
  submitting: boolean;
  onTest: () => void;
}) {
  const { t } = useTranslation();

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
            <IdentityFilePicker value={form.IdentityFile} error={errors.IdentityFile} onChange={(value) => setField("IdentityFile", value)} />
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

export function ConfigEditorPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [entries, setEntries] = useState<SSHConfigCrudEntry[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<SSHConfigCrudEntry>(emptyForm);
  const [addErrors, setAddErrors] = useState<FormErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [configPath, setConfigPath] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setEntries(await configApi.list());
    } catch (e: unknown) {
      toast.error(`${t("config.loadFailed")}: ${e instanceof Error ? e.message : ""}`);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    configApi.path()
      .then(setConfigPath)
      .catch(() => setConfigPath(t("config.configReadFailed")));
  }, [t]);

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return entries;
    return entries.filter((entry) => [entry.host, entry.hostname, entry.user, entry.remarks].some((v) => v.toLowerCase().includes(keyword)));
  }, [entries, search]);

  const validateForm = (form: SSHConfigCrudEntry, options: { requirePassword?: boolean } = {}): FormErrors => {
    const value = normalizeForm(form);
    const errors: FormErrors = {};
    if (!value.host) errors.host = t("config.validation.hostRequired");
    if (!value.hostname) errors.hostname = t("config.validation.hostnameRequired");
    if (!value.user) errors.user = t("config.validation.userRequired");
    if (!Number.isInteger(value.port) || value.port < 1 || value.port > 65535) errors.port = t("config.validation.portRange");
    if (value.type !== "password" && value.type !== "key") errors.type = t("config.validation.typeRequired");
    if (options.requirePassword && value.type === "password" && !value.password) errors.password = t("config.validation.passwordRequired");
    if (value.type === "key" && !value.IdentityFile) errors.IdentityFile = t("config.validation.keyRequired");
    return errors;
  };

  const firstError = (errors: FormErrors): string | undefined => Object.values(errors).find(Boolean);

  const submitAdd = async () => {
    const errors = validateForm(addForm);
    setAddErrors(errors);
    const message = firstError(errors);
    if (message) { toast.error(message); return; }
    setSubmitting(true);
    try {
      const created = await configApi.create(normalizeForm(addForm));
      toast.success(t("config.saveSuccess", { host: created.host }));
      setAddOpen(false);
      setAddForm(emptyForm);
      setAddErrors({});
      await refresh();
      navigate(`/config/${encodeURIComponent(created.host)}`);
    } catch (e: unknown) {
      toast.error(`${t("config.saveFailed")}: ${e instanceof Error ? e.message : ""}`);
    } finally {
      setSubmitting(false);
    }
  };

  const testForm = async (form: SSHConfigCrudEntry, setErrors: (e: FormErrors) => void) => {
    const errors = validateForm(form, { requirePassword: true });
    setErrors(errors);
    const message = firstError(errors);
    if (message) { toast.error(message); return; }
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">{t("config.title")}</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {t("config.configPath")}: <span className="font-mono text-foreground/70">{configPath || t("config.reading")}</span>
          </p>
        </div>
        <Dialog open={addOpen} onOpenChange={(open) => { setAddOpen(open); if (!open) setAddErrors({}); }}>
          <button
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3.5 text-[13px] font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />{t("config.addConfig")}
          </button>
          <DialogContent className="sm:max-w-[560px]">
            <DialogHeader>
              <DialogTitle className="text-[17px]">{t("config.addTitle")}</DialogTitle>
              <DialogDescription className="text-[13px]">{t("config.addDesc")}</DialogDescription>
            </DialogHeader>
            <ConfigFormFields
              form={addForm}
              errors={addErrors}
              onChange={setAddForm}
              testing={testing}
              submitting={submitting}
              onTest={() => testForm(addForm, setAddErrors)}
            />
            <DialogFooter className="mt-2">
              <Button variant="outline" size="sm" onClick={() => setAddOpen(false)}>{t("common.cancel")}</Button>
              <Button size="sm" onClick={submitAdd} disabled={submitting || testing}>{submitting ? t("common.saving") : t("common.save")}</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="apple-group">
        <div className="flex items-center gap-2 px-4 py-2.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <Input
            className="h-8 border-0 bg-transparent px-0 text-[13px] outline-none focus-visible:ring-0"
            placeholder={t("config.filterPlaceholder")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {loading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-muted/50" />)}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="apple-group p-8">
          <EmptyState
            icon={<FileEdit className="h-10 w-10 text-muted-foreground/30" />}
            title={search ? t("config.noMatch") : t("config.noEntries")}
            description=""
          />
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <div className="apple-group">
          {filtered.map((entry, i) => (
            <div key={entry.host}>
              <button
                onClick={() => navigate(`/config/${encodeURIComponent(entry.host)}`)}
                className="w-full flex items-center justify-between px-4 py-3 text-left transition-colors hover:bg-accent/50"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium truncate">{entry.host}</span>
                    <span className="shrink-0 text-[11px] text-muted-foreground">
                      {entry.type === "key" ? t("config.keyType") : t("config.passwordType")}
                    </span>
                  </div>
                  <div className="text-[12px] text-muted-foreground truncate mt-0.5">
                    {entry.user}@{entry.hostname || "?"}:{entry.port}
                    {entry.remarks && <span className="ml-2 opacity-60">{entry.remarks}</span>}
                  </div>
                </div>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
              </button>
              {i < filtered.length - 1 && <Separator />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
