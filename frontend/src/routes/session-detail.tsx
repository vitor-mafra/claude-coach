import { createRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  apiGarmin,
  apiSessions,
  type GarminActivityRow,
  type SessionOut,
} from "@/lib/api";
import { Route as rootRoute } from "./__root";

function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function ActivityBanner({ session }: { session: SessionOut }) {
  const qc = useQueryClient();
  const unlinkMut = useMutation({
    mutationFn: () => apiSessions.setActivity(session.id, null),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session", session.id] }),
  });

  const candidates = useQuery({
    queryKey: ["garmin-activities", session.date],
    queryFn: () => apiGarmin.activities({ start: session.date, end: session.date }),
    enabled: !session.activity,
  });

  const linkMut = useMutation({
    mutationFn: (activityId: number) => apiSessions.setActivity(session.id, activityId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session", session.id] }),
  });

  if (session.activity) {
    return (
      <div className="border border-orange-900/40 bg-orange-950/20 rounded p-3 text-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-semibold text-orange-200">
              Garmin: {session.activity.sport_type ?? "atividade"}
              {session.activity_link_source === "auto" && (
                <span className="ml-2 text-xs text-zinc-500">(match automático)</span>
              )}
            </p>
            <p className="text-zinc-400 text-xs mt-1">
              {session.activity.duration_s
                ? `${Math.round(session.activity.duration_s / 60)} min`
                : ""}
              {session.activity.distance_km ? ` · ${session.activity.distance_km}km` : ""}
              {session.activity.hr_avg ? ` · FC méd ${session.activity.hr_avg}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={() => unlinkMut.mutate()}
            disabled={unlinkMut.isPending}
            className="text-xs text-zinc-400 hover:text-red-300"
          >
            desfazer
          </button>
        </div>
      </div>
    );
  }

  const acts = (candidates.data ?? []) as GarminActivityRow[];
  if (acts.length === 0) {
    return (
      <p className="text-xs text-zinc-500 italic">
        Nenhuma atividade Garmin encontrada nesse dia.
      </p>
    );
  }
  return (
    <div className="border border-zinc-800 rounded p-3 text-sm space-y-2">
      <p className="text-xs text-zinc-500">Vincular atividade Garmin:</p>
      {acts.map((a) => (
        <button
          key={a.activity_id}
          type="button"
          onClick={() => linkMut.mutate(a.activity_id)}
          className="w-full text-left px-2 py-1 rounded hover:bg-zinc-900"
        >
          <span className="font-mono text-xs text-zinc-500">#{a.activity_id}</span>{" "}
          <span>{a.sport_type ?? "?"}</span>
          {a.duration_s ? (
            <span className="text-zinc-500 text-xs ml-2">
              {Math.round(a.duration_s / 60)}min
              {a.distance_km ? ` · ${a.distance_km}km` : ""}
            </span>
          ) : null}
        </button>
      ))}
    </div>
  );
}

function SessionDetailPage() {
  const { id } = Route.useParams();
  const sid = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["session", sid],
    queryFn: () => apiSessions.get(sid),
  });
  const deleteMut = useMutation({
    mutationFn: () => apiSessions.delete(sid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      navigate({ to: "/history" });
    },
  });

  if (isLoading) return <p className="text-sm text-zinc-500">Carregando…</p>;
  if (!data) return <p className="text-sm text-zinc-500">Sessão não encontrada.</p>;

  // group sets by (block_idx, exercise_id)
  const groups = new Map<string, typeof data.sets>();
  for (const s of data.sets) {
    const k = `${s.block_idx}:${s.exercise_id}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(s);
  }

  return (
    <div className="space-y-4">
      <header className="flex justify-between items-baseline">
        <div>
          <h1 className="text-2xl font-bold">{fmtDate(data.date)}</h1>
          <p className="text-sm text-zinc-500">
            {data.plan_slug} · template {data.workout_template_id}
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            if (confirm("Apagar essa sessão?")) deleteMut.mutate();
          }}
          className="text-xs text-zinc-500 hover:text-red-300"
        >
          apagar
        </button>
      </header>

      <ActivityBanner session={data} />

      {data.note && (
        <div className="text-sm bg-zinc-900/40 border border-zinc-800 rounded p-3 whitespace-pre-wrap">
          {data.note}
        </div>
      )}

      <div className="space-y-3">
        {Array.from(groups.entries()).map(([k, sets]) => (
          <div key={k} className="border border-zinc-800 rounded p-3 bg-zinc-900/40">
            <p className="font-semibold text-sm">{sets[0].exercise_id}</p>
            <table className="text-sm w-full mt-2">
              <thead>
                <tr className="text-zinc-500 text-xs">
                  <th className="text-left">set</th>
                  <th className="text-left">reps</th>
                  <th className="text-left">kg</th>
                  <th className="text-left">flags</th>
                </tr>
              </thead>
              <tbody>
                {sets.map((s) => (
                  <tr key={s.set_idx}>
                    <td className="text-zinc-500">#{s.set_idx}</td>
                    <td>
                      {s.actual_reps ?? "—"}
                      {s.planned_reps && s.actual_reps !== s.planned_reps ? (
                        <span className="text-xs text-zinc-600"> /{s.planned_reps}</span>
                      ) : null}
                    </td>
                    <td>{s.actual_weight_kg ?? "—"}</td>
                    <td className="text-xs text-zinc-500">
                      {s.is_warmup ? "aq" : ""}
                      {s.is_dropset_continuation ? " drop" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/session/$id",
  component: SessionDetailPage,
});
