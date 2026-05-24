import { createRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, type Profile, type Weekday } from "@/lib/api";
import { orderedWeekdays, weekdayLabel } from "@/lib/format";
import { Route as rootRoute } from "./__root";

function tanaka(birthdate: string): number {
  if (!birthdate) return 0;
  const d = new Date(birthdate);
  if (Number.isNaN(d.getTime())) return 0;
  const today = new Date();
  let age = today.getFullYear() - d.getFullYear();
  const m = today.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && today.getDate() < d.getDate())) age--;
  return Math.round(208 - 0.7 * age);
}

function ProfilePage() {
  const qc = useQueryClient();
  const existing = useQuery({ queryKey: ["profile"], queryFn: api.profile.get });

  const [draft, setDraft] = useState<Profile>({
    name: "",
    birthdate: "",
    sex: "M",
    height_cm: 175,
    fc_max_bpm: 190,
    fc_max_source: "tanaka",
    training_days: ["mon", "tue", "wed", "thu", "fri"],
  });

  useEffect(() => {
    if (existing.data) setDraft(existing.data);
  }, [existing.data]);

  // Auto-recompute Tanaka when source = tanaka and birthdate changes
  useEffect(() => {
    if (draft.fc_max_source === "tanaka" && draft.birthdate) {
      const v = tanaka(draft.birthdate);
      if (v && v !== draft.fc_max_bpm) {
        setDraft((d) => ({ ...d, fc_max_bpm: v }));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.birthdate, draft.fc_max_source]);

  const mut = useMutation({
    mutationFn: (p: Profile) => api.profile.put(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile"] }),
  });

  function toggleDay(d: Weekday) {
    setDraft((p) => {
      const current = p.training_days ?? [];
      return {
        ...p,
        training_days: current.includes(d)
          ? current.filter((x) => x !== d)
          : [...current, d],
      };
    });
  }

  return (
    <div className="space-y-6 max-w-xl">
      <header>
        <h1 className="text-xl font-bold">Perfil</h1>
        <p className="text-zinc-500 text-sm">
          Salvo em <code className="bg-zinc-900 px-1 rounded">data/profile.yaml</code>
        </p>
      </header>

      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          mut.mutate(draft);
        }}
      >
        <Field label="Nome">
          <input
            className={inputClass}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Nascimento">
            <input
              type="date"
              className={inputClass}
              value={draft.birthdate}
              onChange={(e) => setDraft({ ...draft, birthdate: e.target.value })}
              required
            />
          </Field>
          <Field label="Sexo">
            <select
              className={inputClass}
              value={draft.sex}
              onChange={(e) => setDraft({ ...draft, sex: e.target.value as "M" | "F" })}
            >
              <option value="M">M</option>
              <option value="F">F</option>
            </select>
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Altura (cm)">
            <input
              type="number"
              className={inputClass}
              value={draft.height_cm}
              onChange={(e) => setDraft({ ...draft, height_cm: parseInt(e.target.value) || 0 })}
            />
          </Field>
          <Field label="FCmáx (bpm)">
            <input
              type="number"
              className={inputClass}
              value={draft.fc_max_bpm}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  fc_max_bpm: parseInt(e.target.value) || 0,
                  fc_max_source: "tested",
                })
              }
            />
            <p className="text-xs text-zinc-500 mt-1">
              fonte: {draft.fc_max_source}
              {draft.fc_max_source === "tanaka" && " (calculado automaticamente)"}
            </p>
          </Field>
        </div>

        <Field label="Dias de treino">
          <div className="flex gap-1">
            {orderedWeekdays.map((d) => (
              <button
                type="button"
                key={d}
                onClick={() => toggleDay(d)}
                className={`flex-1 py-2 rounded text-xs font-semibold ${
                  (draft.training_days ?? []).includes(d)
                    ? "bg-orange-500 text-zinc-950"
                    : "bg-zinc-900 text-zinc-500 hover:bg-zinc-800"
                }`}
              >
                {weekdayLabel(d)}
              </button>
            ))}
          </div>
        </Field>

        <button
          type="submit"
          disabled={mut.isPending}
          className="bg-orange-600 hover:bg-orange-500 disabled:opacity-50 px-4 py-2 rounded text-sm font-semibold text-zinc-950"
        >
          {mut.isPending ? "Salvando…" : existing.data ? "Atualizar perfil" : "Criar perfil"}
        </button>
        {mut.isSuccess && (
          <span className="ml-3 text-xs text-orange-300">salvo em data/profile.yaml</span>
        )}
        {mut.error && (
          <span className="ml-3 text-xs text-red-400">erro: {String(mut.error)}</span>
        )}
      </form>
    </div>
  );
}

const inputClass =
  "w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-600";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wider text-zinc-500 block mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/profile",
  component: ProfilePage,
});
