import { Link, Outlet, createRootRoute, useLocation } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, apiAuth, apiLLM } from "@/lib/api";

function HealthBadge() {
  const { data, error } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 15_000,
  });
  if (error) return <span className="text-xs text-red-400">backend offline</span>;
  if (!data) return <span className="text-xs text-zinc-500">…</span>;
  return (
    <span className="text-xs font-mono" title={`v${data.version} · db ${data.db_ok ? "ok" : "err"}`}>
      <span className={data.db_ok ? "text-orange-400" : "text-red-400"}>●</span>{" "}
      <span className="text-zinc-500">v{data.version}</span>
    </span>
  );
}

function LogoutButton() {
  const qc = useQueryClient();
  const me = useQuery({
    queryKey: ["auth-me"],
    queryFn: apiAuth.me,
    staleTime: 60_000,
  });
  const logout = useMutation({
    mutationFn: apiAuth.logout,
    onSuccess: () => {
      qc.clear();
      window.location.replace("/login");
    },
  });
  if (!me.data?.auth_required || !me.data?.authenticated) return null;
  return (
    <button
      type="button"
      onClick={() => logout.mutate()}
      className="text-xs text-zinc-500 hover:text-orange-300"
      title="sair"
    >
      sair
    </button>
  );
}

function UsageBadge() {
  const { data } = useQuery({
    queryKey: ["llm-usage-30"],
    queryFn: () => apiLLM.usage(30),
    refetchInterval: 60_000,
  });
  if (!data) return null;
  const cost = data.total_cost_usd_estimate;
  const formatted = cost < 0.01 ? `$${cost.toFixed(4)}` : `$${cost.toFixed(2)}`;
  return (
    <Link
      to="/usage"
      className="text-xs font-mono text-zinc-500 hover:text-orange-300"
      title={`${data.total_calls} chamadas LLM últimos 30d`}
    >
      {formatted}
    </Link>
  );
}

const linkClass =
  "px-2 py-1 rounded text-sm text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900 " +
  "[&.active]:text-orange-300 [&.active]:bg-orange-950/40";

function Shell() {
  const loc = useLocation();
  if (loc.pathname === "/login") {
    return (
      <div className="min-h-dvh bg-zinc-950 text-zinc-100">
        <div className="max-w-5xl mx-auto p-4">
          <Outlet />
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-dvh bg-zinc-950 text-zinc-100">
      <nav className="border-b border-zinc-800 px-4 py-2 flex items-center gap-2 max-w-5xl mx-auto">
        <Link to="/" className="font-bold text-orange-400 mr-3">
          Claude Coach
        </Link>
        <Link to="/briefing" className={linkClass}>
          Briefing
        </Link>
        <Link to="/history" className={linkClass}>
          Histórico
        </Link>
        <Link to="/reports" className={linkClass}>
          Relatórios
        </Link>
        <Link to="/plans" className={linkClass}>
          Planos
        </Link>
        <Link to="/exercises" className={linkClass}>
          Exercícios
        </Link>
        <Link to="/profile" className={linkClass}>
          Perfil
        </Link>
        <Link to="/settings" className={linkClass}>
          Settings
        </Link>
        <div className="flex-1" />
        <UsageBadge />
        <HealthBadge />
        <LogoutButton />
      </nav>
      <div className="max-w-5xl mx-auto p-4">
        <Outlet />
      </div>
    </div>
  );
}

export const Route = createRootRoute({
  component: Shell,
});
