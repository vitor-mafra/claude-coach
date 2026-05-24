import { createRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { BlockView } from "@/components/BlockView";
import { WeekGrid } from "@/components/WeekGrid";
import { api } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function PlanDetailPage() {
  const { slug } = Route.useParams();
  const qc = useQueryClient();
  const plan = useQuery({ queryKey: ["plan", slug], queryFn: () => api.plans.get(slug) });
  const review = useQuery({
    queryKey: ["plan", slug, "review"],
    queryFn: () => api.plans.review(slug),
    retry: false,
  });

  const regenerate = useMutation({
    mutationFn: () => api.plans.regenerateSchedule(slug),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plan", slug] }),
  });

  if (plan.isLoading) return <p className="text-zinc-500 text-sm">Carregando…</p>;
  if (plan.error) return <p className="text-red-400 text-sm">Erro: {String(plan.error)}</p>;
  if (!plan.data) return null;

  const { templates, schedule, schedule_rationale, name, goal, level } = plan.data;

  return (
    <div className="space-y-6">
      <header>
        <Link to="/plans" className="text-xs text-zinc-500 hover:text-zinc-100">
          ← planos
        </Link>
        <h1 className="text-xl font-bold mt-1">{name}</h1>
        <p className="text-zinc-500 text-sm">
          {level && <>{level} · </>}
          {goal}
        </p>
      </header>

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs uppercase tracking-wider text-zinc-500">Semana</h2>
          <button
            type="button"
            onClick={() => regenerate.mutate()}
            disabled={regenerate.isPending}
            className="text-xs text-orange-300 hover:text-orange-200 disabled:opacity-50"
          >
            {regenerate.isPending ? "regenerando…" : "↻ regenerar agenda"}
          </button>
        </div>
        <WeekGrid schedule={schedule ?? {}} />
        {schedule_rationale && (
          <p className="text-xs text-zinc-500 mt-3 italic">{schedule_rationale}</p>
        )}
      </section>

      {Object.values(templates).map((tpl) => (
        <section key={tpl.template_id}>
          <div className="flex items-baseline gap-2 mb-2">
            <h2 className="text-lg font-semibold">{tpl.template_id}</h2>
            <span className="text-zinc-500 text-sm">{tpl.name}</span>
            <span className="text-xs text-zinc-600 ml-auto">{tpl.kind}</span>
          </div>

          {(tpl.warmups ?? []).length > 0 && (
            <div className="mb-2 border border-orange-900/40 bg-orange-950/10 rounded-lg p-3">
              <p className="text-[10px] uppercase tracking-wider text-orange-300 font-semibold mb-1">
                Preparação · sugestão
              </p>
              <ul className="text-sm space-y-0.5 text-zinc-300">
                {(tpl.warmups ?? []).map((w, i) => (
                  <li key={i}>
                    {w.description}
                    {w.duration_min != null && (
                      <span className="text-zinc-500"> · {w.duration_min}min</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <ul className="space-y-2">
            {tpl.blocks.map((block, i) => (
              <BlockView key={i} block={block} index={i} />
            ))}
          </ul>
        </section>
      ))}

      {review.data && (
        <details className="border border-zinc-800 rounded-lg p-3">
          <summary className="cursor-pointer text-xs uppercase tracking-wider text-zinc-500">
            Import REVIEW.md
          </summary>
          <pre className="mt-3 text-xs whitespace-pre-wrap font-mono text-zinc-400">
            {review.data.content}
          </pre>
        </details>
      )}
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/plan/$slug",
  component: PlanDetailPage,
});
