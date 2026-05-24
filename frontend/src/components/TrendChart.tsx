import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const AXIS = { stroke: "#52525b", fontSize: 10 };
const GRID = "#27272a";
const TOOLTIP_STYLE = {
  backgroundColor: "#18181b",
  border: "1px solid #27272a",
  borderRadius: 6,
  fontSize: 12,
  color: "#e4e4e7",
};
const TOOLTIP_LABEL = { color: "#a1a1aa", marginBottom: 4 };

function fmtDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return `${d.getDate().toString().padStart(2, "0")}/${(d.getMonth() + 1)
    .toString()
    .padStart(2, "0")}`;
}

function fmtDayMonth(d: Date): string {
  return `${d.getDate().toString().padStart(2, "0")}/${(d.getMonth() + 1)
    .toString()
    .padStart(2, "0")}`;
}

/* ──────────────── Sleep (7d, purple bars) ──────────────── */

export function SleepTrend({
  data,
}: {
  data: { date: string; sleep_score: number | null; sleep_duration_min: number | null }[];
}) {
  const rows = data.map((d) => ({
    label: fmtDay(d.date),
    score: d.sleep_score,
    duration_min: d.sleep_duration_min,
  }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={rows} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="label"
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          interval={0}
        />
        <YAxis
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          domain={[0, 100]}
          ticks={[0, 50, 100]}
        />
        <Tooltip
          cursor={{ fill: "#a78bfa15" }}
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL}
          formatter={(v, name, item) => {
            if (name === "score") {
              const mins = (item?.payload as { duration_min?: number | null })
                ?.duration_min;
              if (mins) {
                const h = Math.floor(mins / 60);
                const m = mins % 60;
                return [`${v} · ${h}h${String(m).padStart(2, "0")}min`, "score"];
              }
              return [String(v), "score"];
            }
            return [String(v), String(name)];
          }}
        />
        <Bar dataKey="score" fill="#a78bfa" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ──────────────── HRV (7d, uniform ticks) ──────────────── */

export function HrvTrend({ data }: { data: { date: string; hrv_avg: number | null }[] }) {
  const rows = data.map((d) => ({ label: fmtDay(d.date), hrv: d.hrv_avg }));
  const vals = rows.map((r) => r.hrv).filter((v): v is number => v != null);
  const min = vals.length ? Math.floor(Math.min(...vals) - 5) : 40;
  const max = vals.length ? Math.ceil(Math.max(...vals) + 5) : 100;
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={rows} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="label"
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          interval={0}
        />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} domain={[min, max]} />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL}
          formatter={(v) => [`${v}ms`, "HRV"]}
        />
        <Line
          type="monotone"
          dataKey="hrv"
          stroke="#22c55e"
          strokeWidth={2.5}
          dot={{ r: 3, fill: "#22c55e" }}
          activeDot={{ r: 5 }}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ──────────────── Body Battery intraday (7d curve) ──────────────── */

export function BodyBatteryIntraday({
  data,
}: {
  data: { ts: string; level: number }[];
}) {
  if (data.length === 0) {
    return (
      <div className="h-[180px] flex items-center justify-center text-xs text-zinc-500">
        Sem dados de Body Battery na última semana.
      </div>
    );
  }
  const rows = data.map((p) => {
    const d = new Date(p.ts);
    return {
      t: d.getTime(),
      label: fmtDayMonth(d),
      level: p.level,
    };
  });

  // Compute one tick per day at midnight (local).
  const first = new Date(rows[0].t);
  const last = new Date(rows[rows.length - 1].t);
  const ticks: number[] = [];
  const day = new Date(first);
  day.setHours(0, 0, 0, 0);
  while (day.getTime() <= last.getTime()) {
    ticks.push(day.getTime());
    day.setDate(day.getDate() + 1);
  }

  return (
    <ResponsiveContainer width="100%" height={180}>
      <AreaChart data={rows} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
        <defs>
          <linearGradient id="bbFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#eab308" stopOpacity={0.55} />
            <stop offset="100%" stopColor="#eab308" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          domain={["dataMin", "dataMax"]}
          ticks={ticks}
          tickFormatter={(t) => fmtDayMonth(new Date(t))}
          tick={AXIS}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          domain={[0, 100]}
          ticks={[0, 25, 50, 75, 100]}
        />
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL}
          labelFormatter={(t) =>
            new Date(t as number).toLocaleString("pt-BR", {
              day: "2-digit",
              month: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })
          }
          formatter={(v) => [`${v}`, "BB"]}
        />
        <Area
          type="monotone"
          dataKey="level"
          stroke="#eab308"
          strokeWidth={1.8}
          fill="url(#bbFill)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ──────────────── Weekly volume — force vs run km ──────────────── */

export function WeeklyVolumeChart({
  data,
}: {
  data: {
    week_label: string;
    strength_sessions: number;
    run_km: number;
  }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 6, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis
          dataKey="week_label"
          tick={AXIS}
          axisLine={false}
          tickLine={false}
          interval={0}
        />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} />
        <Tooltip
          cursor={{ fill: "#fb923c10" }}
          contentStyle={TOOLTIP_STYLE}
          labelStyle={TOOLTIP_LABEL}
          formatter={(v, name) =>
            name === "run_km"
              ? [`${v} km`, "corrida"]
              : [`${v} sessões`, "força"]
          }
        />
        <Bar
          dataKey="strength_sessions"
          fill="#fb923c"
          radius={[3, 3, 0, 0]}
          name="Força (sessões)"
        />
        <Bar dataKey="run_km" fill="#22d3ee" radius={[3, 3, 0, 0]} name="Corrida (km)" />
      </BarChart>
    </ResponsiveContainer>
  );
}
