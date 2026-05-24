import { createRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function PlansPage() {
  const plans = useQuery({ queryKey: ["plans"], queryFn: api.plans.list });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Planos importados</h1>

      {plans.isLoading && <p className="text-zinc-500 text-sm">Carregando…</p>}

      {plans.data?.length === 0 && (
        <div className="border border-zinc-800 rounded-lg p-4 text-sm text-zinc-400">
          Nenhum plano ainda. Importe com{" "}
          <code className="bg-zinc-900 px-1 rounded">make parse</code> (requer{" "}
          <code className="bg-zinc-900 px-1 rounded">ANTHROPIC_API_KEY</code>).
        </div>
      )}

      <ul className="space-y-2">
        {plans.data?.map((slug) => (
          <li key={slug}>
            <Link
              to="/plan/$slug"
              params={{ slug }}
              className="block border border-zinc-800 rounded-lg p-4 bg-zinc-900/40 hover:bg-zinc-900"
            >
              <p className="font-mono text-sm">{slug}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/plans",
  component: PlansPage,
});
