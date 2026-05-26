import { createRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { StatCard } from "@/components/StatCard";
import {
  BodyBatteryIntraday,
  HrvTrend,
  SleepTrend,
  WeeklyVolumeChart,
} from "@/components/TrendChart";
import { WeekGrid } from "@/components/WeekGrid";
import {
  api,
  apiAdmin,
  apiDashboard,
  apiGarmin,
  apiWorkouts,
  type TodayCard as TodayCardT,
} from "@/lib/api";
import { Route as rootRoute } from "./__root";

function fmtHours(min: number | null | undefined): string {
  if (!min) return "—";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h}h${String(m).padStart(2, "0")}`;
}

function delta(value: number | null | undefined, avg: number | null | undefined): string {
  if (value == null || avg == null) return "";
  const diff = value - avg;
  const sign = diff >= 0 ? "+" : "";
  return `${sign}${diff.toFixed(1)} vs 7d`;
}

function sleepTone(score: number | null | undefined, avg: number | null | undefined) {
  if (score == null) return "neutral";
  if (score >= 80) return "ok";
  if (score >= 60) return avg != null && score >= avg - 5 ? "warn" : "alert";
  return "alert";
}

function bbTone(bb: number | null | undefined) {
  if (bb == null) return "neutral";
  if (bb >= 60) return "ok";
  if (bb >= 30) return "warn";
  return "alert";
}

function hrvTone(value: number | null | undefined, avg: number | null | undefined) {
  if (value == null || avg == null) return "neutral";
  if (value >= avg - 5) return "ok";
  if (value >= avg - 15) return "warn";
  return "alert";
}

function stressTone(value: number | null | undefined) {
  if (value == null) return "neutral";
  if (value <= 30) return "ok";
  if (value <= 50) return "warn";
  return "alert";
}

function TodayCards({ today }: { today: TodayCardT }) {
  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <StatCard
        label="Body Battery"
        value={today.body_battery_now ?? "—"}
        unit={today.body_battery_now != null ? "/ 100" : undefined}
        hint={
          today.body_battery_start != null
            ? `início do dia: ${today.body_battery_start}`
            : "sem dado"
        }
        tone={bbTone(today.body_battery_now)}
      />
      <StatCard
        label="Sono"
        value={today.sleep_score ?? "—"}
        unit={today.sleep_score != null ? "score" : undefined}
        hint={
          today.sleep_duration_min
            ? `${fmtHours(today.sleep_duration_min)} ${delta(
                today.sleep_score,
                today.sleep_score_7d_avg,
              )}`
            : "sem dado"
        }
        tone={sleepTone(today.sleep_score, today.sleep_score_7d_avg)}
      />
      <StatCard
        label="HRV"
        value={today.hrv_avg ?? "—"}
        unit={today.hrv_avg != null ? "ms" : undefined}
        hint={
          today.hrv_7d_avg != null
            ? `média 7d: ${today.hrv_7d_avg} (${delta(
                today.hrv_avg,
                today.hrv_7d_avg,
              )})`
            : "sem média"
        }
        tone={hrvTone(today.hrv_avg, today.hrv_7d_avg)}
      />
      <StatCard
        label="Stress"
        value={today.stress_avg ?? "—"}
        unit={today.stress_avg != null ? "/ 100" : undefined}
        hint={
          today.stress_7d_avg != null
            ? `média 7d: ${today.stress_7d_avg}`
            : "sem dado"
        }
        tone={stressTone(today.stress_avg)}
      />
    </section>
  );
}

function HomePage() {
  const qc = useQueryClient();
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: apiDashboard.get });
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile.get });
  const plans = useQuery({ queryKey: ["plans"], queryFn: api.plans.list });
  const systemStatus = useQuery({ queryKey: ["admin-system"], queryFn: apiAdmin.system });
  const needsSetup =
    systemStatus.data &&
    (!systemStatus.data.profile_configured ||
      systemStatus.data.plans_count === 0 ||
      !systemStatus.data.garmin_connected);
  const activeSlug = plans.data?.[0];
  const workoutsToday = useQuery({
    queryKey: ["workouts-today-home"],
    queryFn: () => apiWorkouts.today(),
    enabled: !!activeSlug,
  });

  const refresh = useMutation({
    mutationFn: async () => {
      const today = new Date().toISOString().slice(0, 10);
      const yesterday = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
      // Pull yesterday for sleep close-out + today for live metrics.
      await Promise.all([apiGarmin.sync(yesterday), apiGarmin.sync(today)]);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["workouts-today-home"] });
    },
  });

  const today = dashboard.data?.today;
  const trend = dashboard.data?.trend ?? [];
  const bbIntraday = dashboard.data?.body_battery_intraday ?? [];
  const weekly = dashboard.data?.weekly_volume ?? [];
  const acts = dashboard.data?.recent_activities ?? [];

  return (
    <div className="space-y-6">
      <header className="flex justify-between items-baseline gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight">
            {profile.data ? `Olá, ${profile.data.name.split(" ")[0]}` : "Claude Coach"}
          </h1>
          <p className="text-sm text-zinc-500">
            {today?.valid_as_of
              ? `Garmin atualizado ${new Date(today.valid_as_of).toLocaleTimeString(
                  "pt-BR",
                  { hour: "2-digit", minute: "2-digit" },
                )}`
              : "Toque em atualizar pra puxar o Garmin"}
          </p>
        </div>
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="px-3 py-1.5 rounded border border-zinc-800 text-sm text-zinc-300 hover:bg-zinc-900 disabled:opacity-50"
        >
          {refresh.isPending ? "Sincronizando…" : "↻ Atualizar Garmin"}
        </button>
      </header>

      {needsSetup && (
        <div className="border border-amber-900/40 bg-amber-950/20 rounded-lg p-4 text-sm flex flex-wrap items-center gap-3">
          <span className="text-amber-200 font-semibold">Setup incompleto:</span>
          <span className="text-zinc-300 text-xs">
            {!systemStatus.data?.profile_configured && "Perfil "}
            {!systemStatus.data?.garmin_connected && "Garmin "}
            {systemStatus.data?.plans_count === 0 && "Plano "}
            pendente.
          </span>
          <Link
            to="/settings"
            className="ml-auto px-3 py-1.5 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold text-white"
          >
            Abrir Settings →
          </Link>
        </div>
      )}

      {dashboard.isLoading ? (
        <p className="text-zinc-500 text-sm">Carregando…</p>
      ) : today ? (
        <TodayCards today={today} />
      ) : null}

      {/* Quick actions */}
      {activeSlug && (
        <section className="flex gap-2 flex-wrap">
          <Link
            to="/briefing"
            className="px-3 py-2 rounded bg-orange-600 hover:bg-orange-500 font-semibold text-sm"
          >
            Vou treinar agora
          </Link>
          <Link
            to="/session/new"
            className="px-3 py-2 rounded border border-orange-700 text-orange-200 hover:bg-orange-950/40 text-sm"
          >
            Registrar treino
          </Link>
          <Link
            to="/history"
            className="px-3 py-2 rounded border border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-sm"
          >
            Histórico
          </Link>
          <Link
            to="/reports"
            className="px-3 py-2 rounded border border-zinc-800 text-zinc-300 hover:bg-zinc-900 text-sm"
          >
            Relatórios
          </Link>
        </section>
      )}

      {/* Plan + today's workout */}
      {activeSlug && (
        <section className="border border-zinc-800 rounded-lg p-4 bg-zinc-900/40">
          <div className="flex items-baseline justify-between mb-3">
            <div>
              <p className="text-xs uppercase tracking-wider text-zinc-500">Plano ativo</p>
              <p className="font-semibold">{activeSlug}</p>
            </div>
            <Link
              to="/plan/$slug"
              params={{ slug: activeSlug }}
              className="text-sm text-orange-300 hover:text-orange-200"
            >
              ver detalhes →
            </Link>
          </div>

          {workoutsToday.data?.is_rest_day ? (
            <p className="text-sm text-zinc-400">Hoje é dia de descanso.</p>
          ) : workoutsToday.data?.workouts.length ? (
            <div className="space-y-2">
              {workoutsToday.data.workouts.map((w) => (
                <div key={w.template_id} className="text-sm">
                  <p className="font-semibold">{w.name}</p>
                  <p className="text-zinc-500">
                    {w.kind === "run" ? "Corrida" : "Força"} ·{" "}
                    {w.exercises.length} exercícios
                  </p>
                </div>
              ))}
            </div>
          ) : null}

          {plans.data && activeSlug && (
            <PlanWeek slug={activeSlug} />
          )}
        </section>
      )}

      <HRZonesCard />

      <section className="grid lg:grid-cols-2 gap-3">
        <article className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
            Sono (7 dias)
          </h3>
          <SleepTrend data={trend} />
        </article>
        <article className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
            HRV (7 dias)
          </h3>
          <HrvTrend data={trend} />
        </article>
        <article className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40 lg:col-span-2">
          <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
            Body Battery — variação ao longo dos últimos 7 dias
          </h3>
          <BodyBatteryIntraday data={bbIntraday} />
        </article>
        <article className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40 lg:col-span-2 grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-4 items-stretch">
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-1">
              Volume semanal — força (laranja) · corrida km (azul)
            </h3>
            <WeeklyVolumeChart data={weekly} />
          </div>
          <div className="border border-zinc-800 rounded-md p-3 bg-zinc-950/50 sm:min-w-[140px] flex flex-col justify-center">
            <span className="text-xs uppercase tracking-wider text-zinc-500">VO₂ máx</span>
            <span className="text-3xl font-bold text-emerald-300 mt-1">
              {dashboard.data?.vo2_max?.value ?? "—"}
            </span>
            <span className="text-xs text-zinc-500 mt-1">
              {dashboard.data?.vo2_max?.measured_at
                ? `medido em ${dashboard.data.vo2_max.measured_at}`
                : "sem leitura"}
            </span>
          </div>
        </article>
      </section>

      {acts.length > 0 && (
        <section>
          <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
            Atividades recentes
          </h3>
          <ul className="space-y-1">
            {acts.map((a) => (
              <li
                key={a.activity_id}
                className="text-sm border border-zinc-800 rounded px-3 py-2 bg-zinc-900/30 flex justify-between"
              >
                <span>
                  <span className="text-zinc-400">{a.date}</span>{" "}
                  <span className="font-semibold">{a.sport_type ?? "?"}</span>
                </span>
                <span className="text-zinc-500 text-xs">
                  {a.duration_min ? `${a.duration_min}min` : ""}
                  {a.distance_km ? ` · ${a.distance_km}km` : ""}
                  {a.hr_avg ? ` · FC ${a.hr_avg}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function HRZonesCard() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["garmin-hr-zones"],
    queryFn: () => apiGarmin.hrZones(true),
    staleTime: 1000 * 60 * 60 * 24,
  });
  if (isLoading)
    return (
      <article className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40 text-sm text-zinc-500">
        Carregando zonas de FC…
      </article>
    );
  if (error || !data) return null;
  const order: Array<"Z1" | "Z2" | "Z3" | "Z4" | "Z5"> = ["Z1", "Z2", "Z3", "Z4", "Z5"];
  const colors: Record<string, string> = {
    Z1: "bg-emerald-900/40 text-emerald-200",
    Z2: "bg-sky-900/40 text-sky-200",
    Z3: "bg-amber-900/40 text-amber-200",
    Z4: "bg-orange-900/40 text-orange-200",
    Z5: "bg-rose-900/40 text-rose-200",
  };
  return (
    <article className="border border-zinc-800 rounded-lg p-4 bg-zinc-900/40">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-xs uppercase tracking-wider text-zinc-500">
          Zonas de FC (Garmin) · FCmax {data.max_hr}
        </h3>
        <span className="text-[10px] uppercase tracking-wider text-zinc-600">
          {data.training_method}
        </span>
      </div>
      <div className="grid grid-cols-5 gap-2">
        {order.map((z) => {
          const b = data.zone_bounds[z];
          if (!b) return null;
          return (
            <div
              key={z}
              className={`rounded p-2 text-center ${colors[z]}`}
            >
              <div className="text-xs font-semibold">{z}</div>
              <div className="text-sm font-mono">{b[0]}-{b[1]}</div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

function PlanWeek({ slug }: { slug: string }) {
  const { data } = useQuery({
    queryKey: ["plan", slug],
    queryFn: () => api.plans.get(slug),
  });
  if (!data) return null;
  return (
    <div className="mt-4">
      <WeekGrid schedule={data.schedule ?? {}} />
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});
