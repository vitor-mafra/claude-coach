import { createRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { apiSessions, type SessionOut } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" });
}

function SessionCard({ s }: { s: SessionOut }) {
  const total = s.sets.length;
  const completed = s.sets.filter(
    (set) => set.actual_reps != null && set.actual_weight_kg != null,
  ).length;
  const linked = s.garmin_activity_id != null;

  return (
    <Link
      to="/session/$id"
      params={{ id: String(s.id) }}
      className="block border border-zinc-800 rounded-lg p-3 bg-zinc-900/40 hover:border-zinc-700"
    >
      <div className="flex justify-between items-baseline">
        <span className="font-semibold">{fmtDate(s.date)}</span>
        <span className="text-xs text-zinc-500">{s.workout_template_id}</span>
      </div>
      <p className="text-sm text-zinc-400">
        {completed}/{total} sets registrados
      </p>
      {linked && (
        <p className="text-xs text-orange-300 mt-1">
          ⟲ Garmin {s.activity?.sport_type ?? ""}
          {s.activity?.distance_km ? ` · ${s.activity.distance_km}km` : ""}
          {s.activity_link_source === "auto" && " (auto)"}
        </p>
      )}
    </Link>
  );
}

function HistoryPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["sessions"],
    queryFn: () => apiSessions.list({ limit: 50 }),
  });
  return (
    <div className="space-y-4">
      <header className="flex justify-between items-baseline">
        <h1 className="text-2xl font-bold">Histórico</h1>
        <Link
          to="/session/new"
          className="text-sm px-2 py-1 rounded bg-orange-600 hover:bg-orange-500 font-semibold"
        >
          + nova sessão
        </Link>
      </header>
      {isLoading ? (
        <p className="text-zinc-500 text-sm">Carregando…</p>
      ) : !data || data.length === 0 ? (
        <p className="text-zinc-500 text-sm">Nenhuma sessão ainda.</p>
      ) : (
        <div className="space-y-2">
          {data.map((s) => (
            <SessionCard key={s.id} s={s} />
          ))}
        </div>
      )}
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: HistoryPage,
});
