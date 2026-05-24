import type { ReactNode } from "react";

type Tone = "ok" | "warn" | "alert" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "border-emerald-900/40 bg-emerald-950/20",
  warn: "border-amber-900/40 bg-amber-950/20",
  alert: "border-red-900/40 bg-red-950/20",
  neutral: "border-zinc-800 bg-zinc-900/40",
};

const TONE_DOT: Record<Tone, string> = {
  ok: "bg-emerald-400",
  warn: "bg-amber-400",
  alert: "bg-red-400",
  neutral: "bg-zinc-500",
};

export function StatCard({
  label,
  value,
  unit,
  hint,
  tone = "neutral",
  children,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: string;
  tone?: Tone;
  children?: ReactNode;
}) {
  return (
    <div className={`border rounded-lg p-3 sm:p-4 ${TONE_CLASSES[tone]}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`size-1.5 rounded-full ${TONE_DOT[tone]}`} />
        <span className="text-xs uppercase tracking-wider text-zinc-400">{label}</span>
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className="text-2xl sm:text-3xl font-bold text-zinc-50">{value}</span>
        {unit && <span className="text-sm text-zinc-500">{unit}</span>}
      </div>
      {hint && <p className="text-xs text-zinc-400 mt-1">{hint}</p>}
      {children}
    </div>
  );
}
