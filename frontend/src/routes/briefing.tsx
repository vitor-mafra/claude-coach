import { createRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";

import { apiBriefing, type BriefingResponse } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" });
}

function BriefingMarkdown({ data }: { data: BriefingResponse }) {
  return (
    <article
      className={[
        "prose prose-invert prose-sm max-w-none",
        "prose-headings:text-orange-200 prose-headings:font-bold",
        "prose-h3:mt-5 prose-h3:mb-2 prose-h3:text-base prose-h3:uppercase prose-h3:tracking-wider",
        "prose-h3:border-b prose-h3:border-zinc-800 prose-h3:pb-1",
        "prose-strong:text-zinc-100",
        "prose-li:my-0.5",
      ].join(" ")}
    >
      <ReactMarkdown>{data.content_md}</ReactMarkdown>
    </article>
  );
}

function BriefingPage() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["briefings"],
    queryFn: () => apiBriefing.list(10),
  });

  const generate = useMutation({
    mutationFn: () => apiBriefing.generate({ refreshGarmin: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["briefings"] }),
  });

  const latest = useQuery({
    queryKey: ["briefing-latest", list.data?.[0]?.id],
    queryFn: () =>
      list.data?.[0] ? apiBriefing.get(list.data[0].id) : Promise.resolve(null),
    enabled: !!list.data?.[0],
  });

  return (
    <div className="space-y-4">
      <header className="flex justify-between items-baseline">
        <h1 className="text-2xl font-bold">Briefing pré-treino</h1>
        <button
          type="button"
          onClick={() => generate.mutate()}
          disabled={generate.isPending}
          className="px-3 py-2 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
        >
          {generate.isPending ? "Gerando…" : "Vou treinar agora"}
        </button>
      </header>

      {generate.isPending && (
        <p className="text-zinc-500 text-sm italic">
          Sincronizando Garmin e consultando Claude…
        </p>
      )}

      {generate.error && (
        <p className="text-sm text-red-400">{(generate.error as Error).message}</p>
      )}

      {generate.data ? (
        <section className="border border-zinc-800 rounded-lg p-4 bg-zinc-900/40">
          <p className="text-xs text-zinc-500 mb-2">
            {fmtDateTime(generate.data.generated_at)} ·{" "}
            {generate.data.llm_model ?? "—"}
          </p>
          <BriefingMarkdown data={generate.data} />
        </section>
      ) : latest.data ? (
        <section className="border border-zinc-800 rounded-lg p-4 bg-zinc-900/40">
          <p className="text-xs text-zinc-500 mb-2">
            Último briefing: {fmtDateTime(latest.data.generated_at)}
          </p>
          <BriefingMarkdown data={latest.data} />
        </section>
      ) : (
        !list.isLoading && (
          <p className="text-zinc-500 text-sm">
            Nenhum briefing ainda. Clique em "Vou treinar agora" pra gerar o primeiro.
          </p>
        )
      )}

      {list.data && list.data.length > 1 && (
        <section>
          <h2 className="text-sm uppercase text-zinc-500 mb-2">Histórico</h2>
          <div className="space-y-1">
            {list.data.slice(1).map((b) => (
              <Link
                key={b.id}
                to="/briefing/$id"
                params={{ id: String(b.id) }}
                className="block text-sm border border-zinc-800 rounded px-2 py-1 hover:border-zinc-700"
              >
                <span className="text-zinc-400">
                  {b.target_date ? fmtDate(b.target_date) : "—"}
                </span>{" "}
                <span className="text-xs text-zinc-600">
                  · {fmtDateTime(b.generated_at)}
                </span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function BriefingDetailPage() {
  const { id } = DetailRoute.useParams();
  const { data, isLoading } = useQuery({
    queryKey: ["briefing", Number(id)],
    queryFn: () => apiBriefing.get(Number(id)),
  });
  if (isLoading) return <p className="text-sm text-zinc-500">Carregando…</p>;
  if (!data) return <p className="text-sm text-zinc-500">Não encontrado.</p>;
  return (
    <div className="space-y-3">
      <Link to="/briefing" className="text-xs text-zinc-500 hover:text-orange-300">
        ← briefings
      </Link>
      <p className="text-xs text-zinc-500">
        {data.target_date ? fmtDate(data.target_date) : ""} ·{" "}
        {fmtDateTime(data.generated_at)} · {data.llm_model ?? "—"}
      </p>
      <BriefingMarkdown data={data} />
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/briefing",
  component: BriefingPage,
});

export const DetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/briefing/$id",
  component: BriefingDetailPage,
});
