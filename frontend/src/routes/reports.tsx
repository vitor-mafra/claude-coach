import { createRoute, Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import ReactMarkdown from "react-markdown";

import { apiReports, type ReportResponse } from "@/lib/api";
import { Route as rootRoute } from "./__root";

const proseClass = [
  "prose prose-invert prose-sm max-w-none",
  "prose-headings:text-orange-200 prose-headings:font-bold",
  "prose-h2:mt-6 prose-h2:mb-2 prose-h2:text-base prose-h2:uppercase prose-h2:tracking-wider",
  "prose-h2:border-b prose-h2:border-zinc-800 prose-h2:pb-1",
  "prose-strong:text-zinc-100",
  "prose-li:my-0.5",
].join(" ");

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ReportBody({ r }: { r: ReportResponse }) {
  return (
    <article className={proseClass}>
      <ReactMarkdown>{r.content_md}</ReactMarkdown>
    </article>
  );
}

function ReportsPage() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["reports"], queryFn: () => apiReports.list(20) });
  const [sendEmail, setSendEmail] = useState(false);
  const generate = useMutation({
    mutationFn: () => apiReports.generate({ sendEmail }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
  });
  const deleteMut = useMutation({
    mutationFn: (id: number) => apiReports.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
  });

  return (
    <div className="space-y-4">
      <header className="flex justify-between items-baseline flex-wrap gap-3">
        <h1 className="text-2xl font-bold">Relatórios semanais</h1>
        <div className="flex items-center gap-3">
          <label className="text-xs text-zinc-400 flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={sendEmail}
              onChange={(e) => setSendEmail(e.target.checked)}
            />
            Enviar por e-mail
          </label>
          <button
            type="button"
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="px-3 py-2 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
          >
            {generate.isPending ? "Gerando…" : "Gerar agora"}
          </button>
        </div>
      </header>

      <p className="text-xs text-zinc-500">
        Geração automática toda segunda 8h (UTC). Você também pode gerar manualmente.
      </p>

      {generate.error && (
        <p className="text-sm text-red-400">{(generate.error as Error).message}</p>
      )}

      {generate.data && (
        <section className="border border-zinc-800 rounded-lg p-4 bg-zinc-900/40">
          <p className="text-xs text-zinc-500 mb-2">
            Semana {fmtDate(generate.data.week_start)}–{fmtDate(generate.data.week_end)} ·{" "}
            {generate.data.llm_model ?? "—"}
          </p>
          <ReportBody r={generate.data} />
        </section>
      )}

      {list.isLoading ? (
        <p className="text-zinc-500 text-sm">Carregando…</p>
      ) : !list.data || list.data.length === 0 ? (
        <p className="text-zinc-500 text-sm">Nenhum relatório ainda.</p>
      ) : (
        <section className="space-y-1">
          {list.data.map((r) => (
            <div
              key={r.id}
              className="flex items-center border border-zinc-800 rounded hover:border-zinc-700"
            >
              <Link
                to="/reports/$id"
                params={{ id: String(r.id) }}
                className="flex-1 px-3 py-2"
              >
                <span className="font-semibold">
                  {fmtDate(r.week_start)} – {fmtDate(r.week_end)}
                </span>
                <span className="text-xs text-zinc-500 ml-3">
                  gerado {fmtDateTime(r.generated_at)}
                </span>
              </Link>
              <button
                type="button"
                onClick={() => {
                  if (confirm("Apagar esse relatório?")) deleteMut.mutate(r.id);
                }}
                className="px-3 text-xs text-zinc-500 hover:text-red-300"
                title="apagar"
              >
                ✕
              </button>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function ReportDetailPage() {
  const { id } = DetailRoute.useParams();
  const sid = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["report", sid],
    queryFn: () => apiReports.get(sid),
  });
  const deleteMut = useMutation({
    mutationFn: () => apiReports.delete(sid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      navigate({ to: "/reports" });
    },
  });
  if (isLoading) return <p className="text-sm text-zinc-500">Carregando…</p>;
  if (!data) return <p className="text-sm text-zinc-500">Não encontrado.</p>;
  return (
    <div className="space-y-3">
      <Link to="/reports" className="text-xs text-zinc-500 hover:text-orange-300">
        ← relatórios
      </Link>
      <div className="flex justify-between items-baseline">
        <h1 className="text-2xl font-bold">
          Semana {fmtDate(data.week_start)} – {fmtDate(data.week_end)}
        </h1>
        <button
          type="button"
          onClick={() => {
            if (confirm("Apagar esse relatório?")) deleteMut.mutate();
          }}
          className="text-xs text-zinc-500 hover:text-red-300"
        >
          apagar
        </button>
      </div>
      <p className="text-xs text-zinc-500">
        gerado {fmtDateTime(data.generated_at)} · {data.llm_model ?? "—"}
      </p>
      <ReportBody r={data} />
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reports",
  component: ReportsPage,
});

export const DetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reports/$id",
  component: ReportDetailPage,
});
