import { createRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiCalendar, apiMeditation, type CalendarActivity, type CalendarDay } from "@/lib/api";
import { Route as rootRoute } from "./__root";

const WEEK_HEADERS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

const MONTH_NAMES = [
  "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
];

const KIND_DOT: Record<CalendarActivity["kind"], string> = {
  run: "bg-sky-400",
  strength: "bg-orange-400",
  other: "bg-zinc-400",
};

const KIND_LABEL: Record<CalendarActivity["kind"], string> = {
  run: "Corrida",
  strength: "Musculação",
  other: "Outro",
};

const pad = (n: number) => String(n).padStart(2, "0");
const monthKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
const dateKey = (d: Date) => `${monthKey(d)}-${pad(d.getDate())}`;
// Monday-first index: Mon=0 … Sun=6
const mondayIndex = (d: Date) => (d.getDay() + 6) % 7;

function activitySummary(a: CalendarActivity): string {
  const bits: string[] = [];
  if (a.distance_km != null) bits.push(`${a.distance_km} km`);
  if (a.duration_min != null) bits.push(`${a.duration_min} min`);
  return bits.join(" · ");
}

function DayCell({
  day,
  inMonth,
  isToday,
  isPast,
  selected,
  data,
  onClick,
}: {
  day: number;
  inMonth: boolean;
  isToday: boolean;
  isPast: boolean;
  selected: boolean;
  data: CalendarDay | undefined;
  onClick: () => void;
}) {
  const met = data?.goal_met ?? false;
  const planned = data?.planned_count ?? 0;
  const missed = isPast && planned > 0 && !met; // planned but target not hit
  const acts = data?.activities ?? [];
  const meds = data?.meditations ?? [];

  let bg = "bg-zinc-900/30 border-zinc-800";
  if (!inMonth) bg = "bg-transparent border-transparent text-zinc-700";
  else if (met) bg = "bg-emerald-950/50 border-emerald-700/60";
  else if (missed) bg = "bg-red-950/20 border-red-900/40";

  const ring = isToday ? "ring-1 ring-orange-400" : selected ? "ring-1 ring-zinc-400" : "";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!inMonth}
      className={`relative aspect-square rounded-lg border p-1 text-left transition ${bg} ${ring} ${
        inMonth ? "hover:border-zinc-600" : "cursor-default"
      }`}
    >
      <span
        className={`text-xs font-medium ${
          isToday ? "text-orange-300" : inMonth ? "text-zinc-300" : "text-zinc-700"
        }`}
      >
        {day}
      </span>
      {met && (
        <span className="absolute top-1 right-1 text-emerald-400 text-xs leading-none">✓</span>
      )}
      {inMonth && meds.length > 0 && (
        <span className="absolute top-0.5 left-0.5 text-[10px] leading-none">🧘</span>
      )}
      {inMonth && (acts.length > 0 || meds.length > 0 || planned > 0) && (
        <div className="absolute bottom-1 left-1 right-1 flex flex-wrap gap-0.5">
          {acts.slice(0, 4).map((a, i) => (
            <span key={`a${i}`} className={`h-1.5 w-1.5 rounded-full ${KIND_DOT[a.kind]}`} />
          ))}
          {acts.length > 4 && (
            <span className="text-[9px] leading-none text-zinc-400">+{acts.length - 4}</span>
          )}
          {meds.map((_, i) => (
            <span key={`m${i}`} className="h-1.5 w-1.5 rounded-full bg-violet-400" />
          ))}
          {acts.length === 0 &&
            planned > 0 &&
            // planned day with no training done yet: hollow markers
            Array.from({ length: Math.min(planned, 3) }).map((_, i) => (
              <span
                key={`p${i}`}
                className={`h-1.5 w-1.5 rounded-full border ${
                  missed ? "border-red-700" : "border-zinc-600"
                }`}
              />
            ))}
        </div>
      )}
    </button>
  );
}

function CalendarPage() {
  const [cursor, setCursor] = useState(() => {
    const n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), 1);
  });
  const [selected, setSelected] = useState<string | null>(null);

  const [medMin, setMedMin] = useState("");
  const qc = useQueryClient();

  const mk = monthKey(cursor);
  const { data, isLoading } = useQuery({
    queryKey: ["calendar", mk],
    queryFn: () => apiCalendar.get(mk),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["calendar", mk] });
  const addMed = useMutation({
    mutationFn: (min: number | null) =>
      apiMeditation.create({ date: selected!, duration_min: min, source: "manual" }),
    onSuccess: () => {
      setMedMin("");
      invalidate();
    },
  });
  const delMed = useMutation({
    mutationFn: (id: number) => apiMeditation.delete(id),
    onSuccess: invalidate,
  });

  const byDate = useMemo(() => {
    const m = new Map<string, CalendarDay>();
    data?.days.forEach((d) => m.set(d.date, d));
    return m;
  }, [data]);

  const todayKey = dateKey(new Date());

  // Build a 6×7 grid starting on the Monday on/just before the 1st.
  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const start = new Date(first);
    start.setDate(first.getDate() - mondayIndex(first));
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return d;
    });
  }, [cursor]);

  const stats = useMemo(() => {
    let met = 0;
    let planned = 0;
    data?.days.forEach((d) => {
      if (d.planned_count > 0) planned += 1;
      if (d.goal_met) met += 1;
    });
    return { met, planned };
  }, [data]);

  const selectedDay = selected ? byDate.get(selected) : undefined;

  const shift = (delta: number) =>
    setCursor((c) => new Date(c.getFullYear(), c.getMonth() + delta, 1));

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Calendário</h1>
        <span className="text-sm text-zinc-400">
          {stats.met}/{stats.planned} metas no mês
        </span>
      </header>

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => shift(-1)}
          className="px-2 py-1 rounded text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900"
        >
          ‹
        </button>
        <span className="font-semibold">
          {MONTH_NAMES[cursor.getMonth()]} {cursor.getFullYear()}
        </span>
        <button
          type="button"
          onClick={() => shift(1)}
          className="px-2 py-1 rounded text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900"
        >
          ›
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs text-zinc-500">
        {WEEK_HEADERS.map((w) => (
          <span key={w}>{w}</span>
        ))}
      </div>

      {isLoading ? (
        <p className="text-zinc-500 text-sm">Carregando…</p>
      ) : (
        <div className="grid grid-cols-7 gap-1">
          {cells.map((d) => {
            const inMonth = d.getMonth() === cursor.getMonth();
            const dk = dateKey(d);
            return (
              <DayCell
                key={dk}
                day={d.getDate()}
                inMonth={inMonth}
                isToday={dk === todayKey}
                isPast={dk < todayKey}
                selected={dk === selected}
                data={inMonth ? byDate.get(dk) : undefined}
                onClick={() => setSelected(dk)}
              />
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-400">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-sky-400" /> corrida
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-orange-400" /> musculação
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-zinc-400" /> outro
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-violet-400" /> 🧘 meditação
        </span>
        <span className="flex items-center gap-1">
          <span className="text-emerald-400">✓</span> meta batida
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full border border-red-700" /> previsto não feito
        </span>
      </div>

      {selected && (
        <div className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40 space-y-2">
          <div className="flex items-baseline justify-between">
            <h2 className="font-semibold">
              {new Date(`${selected}T00:00:00`).toLocaleDateString("pt-BR", {
                weekday: "long",
                day: "2-digit",
                month: "long",
              })}
            </h2>
            {selectedDay && selectedDay.planned_count > 0 && (
              <span
                className={`text-xs ${selectedDay.goal_met ? "text-emerald-400" : "text-zinc-400"}`}
              >
                {selectedDay.done_count}/{selectedDay.planned_count} previstos
                {selectedDay.goal_met ? " ✓" : ""}
              </span>
            )}
          </div>
          {!selectedDay || selectedDay.activities.length === 0 ? (
            <p className="text-sm text-zinc-500">
              {selectedDay && selectedDay.planned_count > 0
                ? "Nenhuma atividade registrada — dia previsto no plano."
                : "Nenhuma atividade neste dia."}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {selectedDay.activities.map((a, i) => (
                <li key={i} className="flex items-center gap-2 text-sm">
                  <span className={`h-2 w-2 rounded-full shrink-0 ${KIND_DOT[a.kind]}`} />
                  <span className="text-zinc-200">{a.label}</span>
                  {a.source === "linked" && (
                    <span className="text-[10px] text-orange-300/80">⟲ Garmin</span>
                  )}
                  <span className="text-zinc-500 text-xs ml-auto">
                    {activitySummary(a) || KIND_LABEL[a.kind]}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {/* Meditação — track separado */}
          <div className="border-t border-zinc-800 pt-2 space-y-1.5">
            <p className="text-xs font-medium text-violet-300">🧘 Meditação</p>
            {selectedDay?.meditations.map((m) => (
              <div key={m.id} className="flex items-center gap-2 text-sm">
                <span className="h-2 w-2 rounded-full shrink-0 bg-violet-400" />
                <span className="text-zinc-200">
                  {m.duration_min != null ? `${m.duration_min} min` : "sessão"}
                </span>
                {m.note && <span className="text-zinc-500 text-xs truncate">{m.note}</span>}
                <button
                  type="button"
                  onClick={() => delMed.mutate(m.id)}
                  className="ml-auto text-xs text-zinc-500 hover:text-red-400"
                  title="remover"
                >
                  ×
                </button>
              </div>
            ))}
            <div className="flex items-center gap-2 pt-1">
              <input
                type="number"
                inputMode="numeric"
                min={0}
                value={medMin}
                onChange={(e) => setMedMin(e.target.value)}
                placeholder="min"
                className="w-20 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-sm"
              />
              <button
                type="button"
                disabled={addMed.isPending}
                onClick={() =>
                  addMed.mutate(medMin.trim() === "" ? null : Number(medMin))
                }
                className="text-sm px-2 py-1 rounded bg-violet-700 hover:bg-violet-600 font-semibold disabled:opacity-50"
              >
                + meditação
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/calendar",
  component: CalendarPage,
});
