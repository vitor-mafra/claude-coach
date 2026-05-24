import { createRoute, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  apiSessions,
  apiWorkouts,
  type PlannedExercise,
  type PlannedWorkout,
  type SessionCreate,
  type SetInput,
} from "@/lib/api";
import { Route as rootRoute } from "./__root";

type SetState = {
  block_idx: number;
  exercise_id: string;
  set_idx: number;
  planned_reps: number | null;
  actual_reps: string;
  actual_weight_kg: string;
  is_warmup: boolean;
  is_dropset_continuation: boolean;
  note: string;
};

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function buildInitialSets(workout: PlannedWorkout): SetState[] {
  const out: SetState[] = [];
  for (const ex of workout.exercises) {
    for (const s of ex.sets) {
      out.push({
        block_idx: ex.block_idx,
        exercise_id: ex.exercise_id,
        set_idx: s.set_idx,
        planned_reps: s.planned_reps ?? null,
        actual_reps: s.planned_reps ? String(s.planned_reps) : "",
        actual_weight_kg: "",
        is_warmup: s.is_warmup ?? false,
        is_dropset_continuation: false,
        note: "",
      });
    }
  }
  return out;
}

function ExerciseBlock({
  exercise,
  sets,
  setSets,
  noteByEx,
  setNoteByEx,
}: {
  exercise: PlannedExercise;
  sets: SetState[];
  setSets: React.Dispatch<React.SetStateAction<SetState[]>>;
  noteByEx: Record<string, string>;
  setNoteByEx: React.Dispatch<React.SetStateAction<Record<string, string>>>;
}) {
  const exKey = `${exercise.block_idx}:${exercise.exercise_id}`;
  const ownSets = sets.filter(
    (s) => s.block_idx === exercise.block_idx && s.exercise_id === exercise.exercise_id,
  );

  function updateSet(setIdx: number, patch: Partial<SetState>) {
    setSets((prev) =>
      prev.map((s) =>
        s.block_idx === exercise.block_idx &&
        s.exercise_id === exercise.exercise_id &&
        s.set_idx === setIdx
          ? { ...s, ...patch }
          : s,
      ),
    );
  }

  function handleWeightChange(setIdx: number, value: string) {
    // First-set load auto-fills the rest, unless they were already touched.
    setSets((prev) => {
      const isFirst = setIdx === ownSets[0]?.set_idx;
      return prev.map((s) => {
        if (s.block_idx !== exercise.block_idx || s.exercise_id !== exercise.exercise_id) {
          return s;
        }
        if (s.set_idx === setIdx) return { ...s, actual_weight_kg: value };
        if (isFirst && !s.actual_weight_kg) {
          return { ...s, actual_weight_kg: value };
        }
        return s;
      });
    });
  }

  const restTxt = exercise.rest_seconds ? `${exercise.rest_seconds}s desc` : "";
  const kindLabel: Record<string, string> = {
    meta_reps: "séries",
    pyramid: "pirâmide",
    biset: "biset",
    dropset: "dropset",
  };

  return (
    <div className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
      <div className="flex items-baseline justify-between mb-2">
        <div>
          <p className="font-semibold">{exercise.exercise_name}</p>
          <p className="text-xs text-zinc-500">
            {kindLabel[exercise.kind] ?? exercise.kind} · {ownSets.length}× ·{" "}
            {restTxt}
          </p>
        </div>
      </div>
      <div className="space-y-1">
        {ownSets.map((s) => (
          <div key={s.set_idx} className="grid grid-cols-[2rem_1fr_1fr_auto] gap-2 items-center">
            <span className="text-xs text-zinc-500">#{s.set_idx}</span>
            <input
              inputMode="decimal"
              placeholder={s.planned_reps ? `${s.planned_reps} reps` : "reps"}
              value={s.actual_reps}
              onChange={(e) => updateSet(s.set_idx, { actual_reps: e.target.value })}
              className="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
            />
            <input
              inputMode="decimal"
              placeholder="kg"
              value={s.actual_weight_kg}
              onChange={(e) => handleWeightChange(s.set_idx, e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
            />
            <label className="text-xs text-zinc-500 flex items-center gap-1">
              <input
                type="checkbox"
                checked={s.is_warmup}
                onChange={(e) => updateSet(s.set_idx, { is_warmup: e.target.checked })}
              />
              aq
            </label>
          </div>
        ))}
      </div>
      <textarea
        placeholder="Nota (opcional)"
        value={noteByEx[exKey] ?? ""}
        onChange={(e) => setNoteByEx((p) => ({ ...p, [exKey]: e.target.value }))}
        rows={2}
        className="mt-2 w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
      />
    </div>
  );
}

function SessionNewPage() {
  const navigate = useNavigate();
  const [date, setDate] = useState(todayISO());
  const { data, isLoading } = useQuery({
    queryKey: ["workouts-today", date],
    queryFn: () => apiWorkouts.today(date),
  });

  const workouts = data?.workouts ?? [];
  const [selectedIdx, setSelectedIdx] = useState(0);
  const workout = workouts[selectedIdx];

  const [sets, setSets] = useState<SetState[]>([]);
  const [noteByEx, setNoteByEx] = useState<Record<string, string>>({});
  const [sessionNote, setSessionNote] = useState("");

  useEffect(() => {
    if (workout) {
      setSets(buildInitialSets(workout));
      setNoteByEx({});
    }
  }, [workout?.template_id, workout?.date]); // eslint-disable-line react-hooks/exhaustive-deps

  const mutation = useMutation({
    mutationFn: (payload: SessionCreate) => apiSessions.create(payload),
    onSuccess: (resp) => navigate({ to: "/session/$id", params: { id: String(resp.id) } }),
  });

  const groupedExercises = useMemo(() => workout?.exercises ?? [], [workout]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!workout) return;
    const payloadSets: SetInput[] = sets.map((s) => ({
      block_idx: s.block_idx,
      exercise_id: s.exercise_id,
      set_idx: s.set_idx,
      planned_reps: s.planned_reps ?? null,
      actual_reps: s.actual_reps ? Number(s.actual_reps) : null,
      actual_weight_kg: s.actual_weight_kg ? Number(s.actual_weight_kg) : null,
      is_warmup: s.is_warmup,
      is_dropset_continuation: s.is_dropset_continuation,
      note: noteByEx[`${s.block_idx}:${s.exercise_id}`] || null,
    }));
    mutation.mutate({
      plan_slug: workout.plan_slug,
      workout_template_id: workout.template_id,
      date: workout.date,
      status: "done",
      note: sessionNote || null,
      started_at: null,
      finished_at: new Date().toISOString(),
      sets: payloadSets,
    });
  }

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Registrar sessão</h1>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
        />
      </header>

      {isLoading ? (
        <p className="text-zinc-500 text-sm">Carregando treino do dia…</p>
      ) : !data?.plan_slug ? (
        <p className="text-zinc-500 text-sm">
          Nenhum plano ativo. Importe um plano antes.
        </p>
      ) : data.is_rest_day ? (
        <p className="text-zinc-500 text-sm">Dia de descanso segundo o cronograma.</p>
      ) : !workout ? (
        <p className="text-zinc-500 text-sm">Sem treino para essa data.</p>
      ) : (
        <>
          {workouts.length > 1 && (
            <div className="flex gap-2">
              {workouts.map((w, i) => (
                <button
                  key={`${w.template_id}-${i}`}
                  type="button"
                  onClick={() => setSelectedIdx(i)}
                  className={
                    "px-2 py-1 rounded text-sm border " +
                    (i === selectedIdx
                      ? "border-orange-600 bg-orange-950/40 text-orange-200"
                      : "border-zinc-800 text-zinc-400")
                  }
                >
                  {w.name}
                </button>
              ))}
            </div>
          )}

          <div className="text-sm text-zinc-400">
            <p className="font-semibold text-zinc-200">{workout.name}</p>
            <p>
              {workout.kind === "run" ? "Corrida" : "Força"} ·{" "}
              {groupedExercises.length} exercícios
            </p>
          </div>

          {workout.kind === "run" ? (
            <p className="text-sm text-zinc-500 border border-zinc-800 rounded p-3">
              Corrida é registrada via Garmin. Após o sync, ela aparece auto-vinculada
              no histórico.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              {groupedExercises.map((ex) => (
                <ExerciseBlock
                  key={`${ex.block_idx}-${ex.exercise_id}`}
                  exercise={ex}
                  sets={sets}
                  setSets={setSets}
                  noteByEx={noteByEx}
                  setNoteByEx={setNoteByEx}
                />
              ))}

              <textarea
                placeholder="Nota geral da sessão (opcional)"
                value={sessionNote}
                onChange={(e) => setSessionNote(e.target.value)}
                rows={2}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-sm"
              />

              <div className="flex justify-end gap-2">
                <button
                  type="submit"
                  disabled={mutation.isPending}
                  className="px-3 py-2 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
                >
                  {mutation.isPending ? "Salvando…" : "Salvar sessão"}
                </button>
              </div>
              {mutation.error && (
                <p className="text-sm text-red-400">{(mutation.error as Error).message}</p>
              )}
            </form>
          )}
        </>
      )}
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/session/new",
  component: SessionNewPage,
});
