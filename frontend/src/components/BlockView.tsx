import type { Block, ExerciseRef } from "@/lib/api";
import { formatRest, formatSegment } from "@/lib/format";

function ExName({ ref }: { ref: ExerciseRef }) {
  if (ref.exercise_id) {
    return (
      <span
        className="font-medium text-zinc-100"
        title={`matched: ${ref.exercise_id} (${ref.confidence?.toFixed(2)})`}
      >
        {ref.raw_name}
      </span>
    );
  }
  return (
    <span className="font-medium text-amber-300" title="no catalog match">
      {ref.raw_name} <sup className="text-amber-500">?</sup>
    </span>
  );
}

function BlockHeader({ tag, color }: { tag: string; color: string }) {
  return (
    <span
      className="inline-block rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider font-semibold"
      style={{ backgroundColor: color + "33", color }}
    >
      {tag}
    </span>
  );
}

const REST = ({
  block,
}: {
  block: { rest?: { seconds?: number | null; min_seconds?: number | null; max_seconds?: number | null; note?: string | null } | null };
}) => {
  const r = block.rest;
  if (!r) return null;
  const text = formatRest(r);
  if (!text) return null;
  return <span className="text-xs text-zinc-500">descanso {text}</span>;
};

export function BlockView({ block, index }: { block: Block; index: number }) {
  const num = String(index + 1).padStart(2, "0");

  switch (block.kind) {
    case "meta_reps":
      return (
        <li className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 font-mono">B{num}</span>
            <BlockHeader tag="meta-reps" color="#34d399" />
            <REST block={block} />
          </div>
          <p className="text-sm">
            {block.sets}×{block.reps} <ExName ref={block.exercise} />
          </p>
        </li>
      );
    case "pyramid":
      return (
        <li className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 font-mono">B{num}</span>
            <BlockHeader tag="pirâmide" color="#a78bfa" />
            <REST block={block} />
          </div>
          <p className="text-sm">
            {block.reps_per_set.join("-")} <ExName ref={block.exercise} />
          </p>
        </li>
      );
    case "biset":
      return (
        <li className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 font-mono">B{num}</span>
            <BlockHeader tag="bi-set" color="#60a5fa" />
            <REST block={block} />
          </div>
          <p className="text-sm">
            {block.rounds}× ·{" "}
            {block.exercises.map((e, i) => (
              <span key={i}>
                {i > 0 && " + "}
                {e.reps} <ExName ref={e.exercise} />
              </span>
            ))}
          </p>
        </li>
      );
    case "dropset":
      return (
        <li className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 font-mono">B{num}</span>
            <BlockHeader tag="dropset" color="#f472b6" />
            <REST block={block} />
          </div>
          <p className="text-sm">
            {block.sets}× <ExName ref={block.exercise} />
            {block.description && (
              <span className="text-zinc-500"> · {block.description}</span>
            )}
          </p>
        </li>
      );
    case "tabata":
      return (
        <li className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 font-mono">B{num}</span>
            <BlockHeader tag="tabata" color="#fb923c" />
          </div>
          <p className="text-sm">
            {block.rounds}× · {block.work_s}s on / {block.rest_s}s off ×{" "}
            {block.rounds_per_set} · {block.description}
          </p>
        </li>
      );
    case "interval_run":
    case "continuous_run":
    case "fartlek": {
      const label = {
        interval_run: "intervalado",
        continuous_run: "contínuo",
        fartlek: "fartlek",
      }[block.kind];
      return (
        <li className="border border-zinc-800 rounded-lg p-3 bg-zinc-900/40">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-zinc-500 font-mono">B{num}</span>
            <BlockHeader tag={label} color="#10b981" />
          </div>
          {block.name && <p className="text-sm text-zinc-300 mb-1">{block.name}</p>}
          <ul className="text-sm font-mono text-zinc-400 space-y-0.5">
            {block.segments.map((s, i) => (
              <li key={i}>{formatSegment(s)}</li>
            ))}
          </ul>
        </li>
      );
    }
  }
}
