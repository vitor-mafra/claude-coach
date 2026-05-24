import { createRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiAuth, HttpError } from "@/lib/api";
import { Route as rootRoute } from "./__root";

function LoginPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const search = useSearch({ from: "/login" }) as { next?: string };
  const [password, setPassword] = useState("");

  const login = useMutation({
    mutationFn: (pw: string) => apiAuth.login(pw),
    onSuccess: () => {
      qc.invalidateQueries();
      const next = search.next ?? "/";
      navigate({ to: next as "/", replace: true });
    },
  });

  const msg =
    login.error instanceof HttpError && login.error.status === 429
      ? "Muitas tentativas. Espera 1 minuto."
      : login.error
        ? "Senha incorreta."
        : null;

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate(password);
        }}
        className="w-full max-w-xs space-y-3 border border-zinc-800 rounded-lg p-5 bg-zinc-900/40"
      >
        <h1 className="text-xl font-bold">Claude Coach</h1>
        <p className="text-sm text-zinc-400">Acesso restrito.</p>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="senha"
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={login.isPending || !password}
          className="w-full px-3 py-2 rounded bg-orange-600 hover:bg-orange-500 text-sm font-semibold disabled:opacity-50"
        >
          {login.isPending ? "Entrando…" : "Entrar"}
        </button>
        {msg && <p className="text-sm text-red-400">{msg}</p>}
      </form>
    </div>
  );
}

export const Route = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
  validateSearch: (s: Record<string, unknown>) => ({
    next: typeof s.next === "string" ? s.next : undefined,
  }),
});
