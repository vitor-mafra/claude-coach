import { createRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { apiAdmin, HttpError, type SystemStatus } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs " +
        (ok
          ? "bg-emerald-950/40 text-emerald-300 border border-emerald-900/40"
          : "bg-zinc-900 text-zinc-400 border border-zinc-800")
      }
    >
      <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-zinc-500"}`} />
      {label}
    </span>
  );
}

function Section({
  title,
  children,
  hint,
}: {
  title: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <section className="border border-zinc-800 rounded-lg p-4 bg-zinc-900/40 space-y-3">
      <header>
        <h2 className="text-sm uppercase tracking-wider text-zinc-400">{title}</h2>
        {hint && <p className="text-xs text-zinc-500 mt-1">{hint}</p>}
      </header>
      {children}
    </section>
  );
}

function SystemOverview({ s }: { s: SystemStatus }) {
  return (
    <div className="grid sm:grid-cols-2 gap-2 text-sm">
      <Badge ok={s.profile_configured} label={`Perfil ${s.profile_configured ? "ok" : "vazio"}`} />
      <Badge ok={s.plans_count > 0} label={`${s.plans_count} plano(s)`} />
      <Badge ok={s.garmin_connected} label={`Garmin ${s.garmin_connected ? "conectado" : "off"}`} />
      <Badge ok={s.llm_provider_keys.openai || s.llm_provider_keys.anthropic} label="LLM key" />
      <Badge ok={s.resend_configured} label="Resend (e-mail)" />
      <span className="text-xs text-zinc-500 col-span-full">
        DB: {s.db_sessions} sessões · {s.db_daily_metrics} dias Garmin ·{" "}
        {s.db_garmin_activities} atividades · {s.db_insights} insights
      </span>
      <span className="text-xs text-zinc-600 col-span-full font-mono">data_dir: {s.data_dir}</span>
    </div>
  );
}

function GarminCard({ s }: { s: SystemStatus }) {
  const qc = useQueryClient();
  const [mfa, setMfa] = useState("");
  const [showMfa, setShowMfa] = useState(false);

  const connect = useMutation({
    mutationFn: (code?: string) =>
      apiAdmin.garminConnect(code ? { mfaCode: code } : undefined),
    onSuccess: (resp) => {
      if (resp.needs_mfa) {
        setShowMfa(true);
      } else {
        setShowMfa(false);
        setMfa("");
      }
      qc.invalidateQueries({ queryKey: ["admin-system"] });
    },
  });

  const disconnect = useMutation({
    mutationFn: () => apiAdmin.garminDisconnect(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-system"] }),
  });

  return (
    <Section
      title="Garmin"
      hint={
        s.garmin_credentials_present
          ? "GARMIN_EMAIL e GARMIN_PASSWORD já configurados via env."
          : "Configure GARMIN_EMAIL e GARMIN_PASSWORD nas variáveis de ambiente do Railway antes de conectar."
      }
    >
      <div className="flex items-center gap-3">
        <Badge ok={s.garmin_connected} label={s.garmin_connected ? "conectado" : "desconectado"} />
        {!s.garmin_connected && (
          <button
            type="button"
            disabled={!s.garmin_credentials_present || connect.isPending}
            onClick={() => connect.mutate(undefined)}
            className="px-3 py-1.5 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
          >
            {connect.isPending ? "Conectando…" : "Conectar Garmin"}
          </button>
        )}
        {s.garmin_connected && (
          <button
            type="button"
            disabled={disconnect.isPending}
            onClick={() => {
              if (confirm("Desconectar Garmin? Vai precisar refazer login.")) disconnect.mutate();
            }}
            className="px-3 py-1.5 rounded border border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-sm disabled:opacity-50"
          >
            Desconectar
          </button>
        )}
      </div>

      {showMfa && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            connect.mutate(mfa);
          }}
          className="border border-amber-900/40 bg-amber-950/20 rounded p-3 space-y-2"
        >
          <p className="text-sm text-amber-200">
            Garmin pediu MFA. Confere seu e-mail e cola o código aqui (cada tentativa dispara
            um código novo).
          </p>
          <div className="flex gap-2">
            <input
              inputMode="numeric"
              value={mfa}
              onChange={(e) => setMfa(e.target.value)}
              placeholder="código MFA"
              className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
            />
            <button
              type="submit"
              disabled={!mfa || connect.isPending}
              className="px-3 py-1 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
            >
              Enviar
            </button>
          </div>
        </form>
      )}

      {connect.data?.detail && !connect.data.needs_mfa && (
        <p className="text-xs text-zinc-500">{connect.data.detail}</p>
      )}
      {connect.error && (
        <p className="text-sm text-red-400">
          {connect.error instanceof HttpError
            ? `erro ${connect.error.status}: ${connect.error.message}`
            : (connect.error as Error).message}
        </p>
      )}
    </Section>
  );
}

function ProfileCard({ s }: { s: SystemStatus }) {
  return (
    <Section title="Perfil">
      <div className="flex items-center gap-3">
        <Badge
          ok={s.profile_configured}
          label={s.profile_configured ? "configurado" : "não configurado"}
        />
        <Link
          to="/profile"
          className="px-3 py-1.5 rounded border border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-sm"
        >
          {s.profile_configured ? "Editar" : "Configurar agora"}
        </Link>
      </div>
    </Section>
  );
}

function PlanUploadCard({ s }: { s: SystemStatus }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [slug, setSlug] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const upload = useMutation({
    mutationFn: () => apiAdmin.uploadPlan(file!, slug || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-system"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
      setFile(null);
      setSlug("");
      if (inputRef.current) inputRef.current.value = "";
    },
  });

  return (
    <Section
      title="Plano (PDF)"
      hint={
        s.profile_configured
          ? "Plano + cronograma serão inferidos automaticamente do PDF."
          : "Configure o perfil primeiro pra inferir o cronograma. Sem perfil, o plano é salvo só com os templates."
      }
    >
      <p className="text-sm text-zinc-400">
        {s.plans_count > 0
          ? `Ativo: ${s.active_plan_slug}. Subir outro PDF substitui se o slug bater.`
          : "Nenhum plano importado ainda."}
      </p>
      <div className="flex flex-col sm:flex-row gap-2 items-start">
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm flex-1"
        />
        <input
          type="text"
          placeholder="slug (opcional)"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          className="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
        />
        <button
          type="button"
          disabled={!file || upload.isPending}
          onClick={() => upload.mutate()}
          className="px-3 py-1.5 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
        >
          {upload.isPending ? "Parseando…" : "Enviar e parsear"}
        </button>
      </div>
      {upload.data && (
        <p className="text-sm text-emerald-300">
          ✓ {upload.data.slug} salvo. {upload.data.scheduled ? "Cronograma OK." : "(sem cronograma)"}{" "}
          —{" "}
          <Link
            to="/plan/$slug"
            params={{ slug: upload.data.slug }}
            className="underline text-orange-300"
          >
            ver plano
          </Link>
        </p>
      )}
      {upload.error && (
        <p className="text-sm text-red-400">
          {(upload.error as Error).message}
        </p>
      )}
    </Section>
  );
}

function GarminBackfillCard({ s }: { s: SystemStatus }) {
  const qc = useQueryClient();
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10);
  const [start, setStart] = useState(monthAgo);
  const [end, setEnd] = useState(today);
  const backfill = useMutation({
    mutationFn: () => apiAdmin.garminBackfill(start, end),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-system"] }),
  });
  if (!s.garmin_connected) return null;
  return (
    <Section title="Backfill Garmin" hint="Roda sync_day pra cada dia no intervalo.">
      <div className="flex flex-wrap gap-2 items-end">
        <label className="text-xs text-zinc-400">
          início
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="block bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
          />
        </label>
        <label className="text-xs text-zinc-400">
          fim
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="block bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
          />
        </label>
        <button
          type="button"
          disabled={backfill.isPending}
          onClick={() => backfill.mutate()}
          className="px-3 py-1.5 rounded border border-orange-700 text-orange-200 hover:bg-orange-950/40 text-sm disabled:opacity-50"
        >
          {backfill.isPending ? "Sincronizando…" : "Rodar backfill"}
        </button>
      </div>
      {backfill.data && (
        <p className="text-sm">
          {backfill.data.ok}/{backfill.data.days} dias OK.{" "}
          {backfill.data.errors.length > 0 && (
            <span className="text-red-400">
              {backfill.data.errors.length} erro(s) — ver logs.
            </span>
          )}
        </p>
      )}
      {backfill.error && (
        <p className="text-sm text-red-400">{(backfill.error as Error).message}</p>
      )}
    </Section>
  );
}

function SettingsPage() {
  const status = useQuery({
    queryKey: ["admin-system"],
    queryFn: apiAdmin.system,
    refetchInterval: 15_000,
  });

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold">Configurações</h1>
        <p className="text-sm text-zinc-500">
          Setup inicial e administração da instância.
        </p>
      </header>

      {status.data && <SystemOverview s={status.data} />}

      {status.data && (
        <div className="grid lg:grid-cols-2 gap-3">
          <ProfileCard s={status.data} />
          <GarminCard s={status.data} />
          <PlanUploadCard s={status.data} />
          <GarminBackfillCard s={status.data} />
        </div>
      )}
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});
