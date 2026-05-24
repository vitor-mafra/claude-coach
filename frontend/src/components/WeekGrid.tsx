import type { Schedule } from "@/lib/api";
import { orderedWeekdays, weekdayLabel } from "@/lib/format";

export function WeekGrid({ schedule }: { schedule: Schedule }) {
  return (
    <div className="grid grid-cols-7 gap-1 text-center text-xs">
      {orderedWeekdays.map((w) => {
        const entries = schedule[w] ?? [];
        const isRest = entries.length === 0;
        return (
          <div
            key={w}
            className={`rounded p-2 min-h-[64px] flex flex-col items-center ${
              isRest ? "bg-zinc-900 text-zinc-600" : "bg-zinc-800"
            }`}
          >
            <div className="text-zinc-500 mb-1">{weekdayLabel(w)}</div>
            {isRest ? (
              <div className="text-zinc-700">—</div>
            ) : (
              <div className="flex flex-col gap-1 w-full">
                {entries.map((tid, i) => (
                  <div
                    key={i}
                    className="font-semibold bg-zinc-900/60 rounded px-1 py-0.5 text-[11px] truncate"
                    title={tid}
                  >
                    {tid}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
