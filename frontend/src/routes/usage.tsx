import { createRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { apiLLM } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function UsagePage() {
  const usage = useQuery({ queryKey: ["llm-usage"], queryFn: () => apiLLM.usage(30) });

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-bold">Uso da LLM</h1>
        <p className="text-zinc-500 text-sm">últimos {usage.data?.range_days ?? 30} dias</p>
      </header>

      {usage.isLoading && <p className="text-zinc-500 text-sm">Carregando…</p>}
      {usage.error && <p className="text-red-400 text-sm">Erro: {String(usage.error)}</p>}

      {usage.data && (
        <>
          <section className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <Stat label="Chamadas" value={usage.data.total_calls.toString()} />
            <Stat
              label="Custo total"
              value={fmtUsd(usage.data.total_cost_usd_estimate)}
              accent
            />
            <Stat
              label="Tokens entrada"
              value={usage.data.total_input_tokens.toLocaleString("pt-BR")}
            />
            <Stat
              label="Tokens saída"
              value={usage.data.total_output_tokens.toLocaleString("pt-BR")}
            />
          </section>

          <section className="border border-zinc-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-zinc-900 text-zinc-500 text-xs uppercase tracking-wider">
                <tr>
                  <th className="text-left p-2">Task</th>
                  <th className="text-right p-2">Chamadas</th>
                  <th className="text-right p-2">In</th>
                  <th className="text-right p-2">Out</th>
                  <th className="text-right p-2">Custo</th>
                </tr>
              </thead>
              <tbody>
                {usage.data.by_task.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-center text-zinc-500 p-4">
                      Nenhuma chamada registrada ainda.
                    </td>
                  </tr>
                )}
                {usage.data.by_task.map((row) => (
                  <tr key={row.task_id} className="border-t border-zinc-800">
                    <td className="p-2 font-mono">{row.task_id}</td>
                    <td className="p-2 text-right">{row.calls}</td>
                    <td className="p-2 text-right text-zinc-400">
                      {row.input_tokens.toLocaleString("pt-BR")}
                    </td>
                    <td className="p-2 text-right text-zinc-400">
                      {row.output_tokens.toLocaleString("pt-BR")}
                    </td>
                    <td className="p-2 text-right text-orange-300 font-mono">
                      {fmtUsd(row.cost_usd_estimate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <p className="text-xs text-zinc-600">
            Custos calculados a partir de uma tabela estática em{" "}
            <code className="bg-zinc-900 px-1 rounded">adapters/llm/pricing.py</code>. Modelos sem
            preço cadastrado aparecem como —.
          </p>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
      <p className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</p>
      <p
        className={`text-lg font-bold font-mono mt-1 ${accent ? "text-orange-300" : "text-zinc-100"}`}
      >
        {value}
      </p>
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/usage",
  component: UsagePage,
});
