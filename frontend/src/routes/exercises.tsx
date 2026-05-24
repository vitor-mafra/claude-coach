import { createRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function ExercisesPage() {
  const [query, setQuery] = useState("");
  const exercises = useQuery({ queryKey: ["exercises"], queryFn: api.exercises.list });

  const filtered = (exercises.data ?? []).filter((e) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      e.name.toLowerCase().includes(q) ||
      (e.aliases ?? []).some((a) => a.toLowerCase().includes(q)) ||
      e.primary_muscle_group.includes(q) ||
      e.equipment.includes(q)
    );
  });

  return (
    <div className="space-y-4">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-bold">Catálogo de exercícios</h1>
        <span className="text-xs text-zinc-500">
          {filtered.length} / {exercises.data?.length ?? 0}
        </span>
      </header>

      <input
        type="search"
        placeholder="buscar por nome, grupo, equipamento…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full bg-zinc-900 border border-zinc-800 rounded px-3 py-2 text-sm placeholder-zinc-600 focus:outline-none focus:border-zinc-600"
      />

      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {filtered.map((ex) => (
          <li
            key={ex.id}
            className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40"
          >
            <p className="font-semibold text-sm">{ex.name}</p>
            <p className="text-xs text-zinc-500 mt-0.5">
              {ex.primary_muscle_group} · {ex.equipment}
            </p>
            {(ex.aliases ?? []).length > 0 && (
              <p
                className="text-xs text-zinc-600 mt-1 font-mono truncate"
                title={(ex.aliases ?? []).join(" / ")}
              >
                {(ex.aliases ?? []).slice(0, 3).join(" / ")}
                {(ex.aliases ?? []).length > 3 && " …"}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/exercises",
  component: ExercisesPage,
});
