"use client";

import { motion, useReducedMotion } from "motion/react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge, Empty } from "@/components/ui/Instrument";
import type { Comparison } from "@/lib/types";

const AXIS = {
  stroke: "rgba(151,163,161,0.3)",
  tick: { fill: "#64716f", fontSize: 10, fontFamily: "var(--font-mono)" },
};

const TOOLTIP_STYLE = {
  background: "#161f23",
  border: "1px solid rgba(0,0,0,0.6)",
  borderRadius: 5,
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  color: "#e6e0d3",
  boxShadow: "0 8px 22px -8px rgba(0,0,0,0.8)",
};

export function ComparisonView({
  comparison,
  selectedId,
  onSelect,
}: {
  comparison: Comparison | null;
  selectedId?: string | null;
  onSelect?: (experimentId: string) => void;
}) {
  const reduced = useReducedMotion();

  if (!comparison || comparison.rows.length === 0) {
    return <Empty>No completed experiments to compare yet.</Empty>;
  }

  // Not every domain reports F1; rank, label and tabulate on what was measured.
  const primaryKey = comparison.primaryMetric ?? "f1";
  const COUNTS = new Set([
    "true_positives", "false_positives", "false_negatives", "true_negatives",
    "n_test", "n_train",
  ]);
  // Columns follow the metrics the run produced, so a pathfinding run shows
  // path cost and expanded nodes rather than empty precision/recall.
  const present = new Set<string>();
  comparison.rows.forEach((r) => Object.keys(r.metrics).forEach((k) => present.add(k)));
  const PREFERRED = [
    "path_cost", "optimality_gap_percent", "expanded_nodes",
    "precision", "recall", "false_positive_rate",
  ];
  const secondary = PREFERRED.filter(
    (m) => present.has(m) && m !== primaryKey && !COUNTS.has(m),
  ).slice(0, 3);

  // The trajectory chart tracks whichever "cost of speed" metric exists.
  const trajectoryKey = present.has("optimality_gap_percent")
    ? "optimality_gap_percent"
    : present.has("false_positive_rate")
      ? "false_positive_rate"
      : null;
  const pretty = (name: string) =>
    name
      .replace(/_percent$/, " %")
      .replace(/_ms$/, " (ms)")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
      .replace(/\bF1\b/i, "F1")
      .replace(/\bFpr\b/i, "FPR");
  const primaryLabel = pretty(primaryKey);
  const fmt = (name: string, value: number | undefined) => {
    if (value === undefined) return "—";
    if (name === "false_positive_rate") return `${(value * 100).toFixed(2)}%`;
    if (name.endsWith("_percent")) return `${value.toFixed(2)}%`;
    if (Number.isInteger(value)) return String(value);
    return Math.abs(value) >= 100 ? value.toFixed(2) : value.toPrecision(4);
  };

  const chartData = comparison.rows.map((row) => ({
    name: `EXP-${String(row.index).padStart(3, "0")}`,
    [primaryLabel]: Number((row.metrics[primaryKey] ?? 0).toPrecision(4)),
    ...Object.fromEntries(
      secondary.map((m) => [
        pretty(m),
        Number(((m === "false_positive_rate" ? 100 : 1) * (row.metrics[m] ?? 0)).toPrecision(4)),
      ]),
    ),
    Trajectory: trajectoryKey
      ? Number(
          ((trajectoryKey === "false_positive_rate" ? 100 : 1) *
            (row.metrics[trajectoryKey] ?? 0)).toPrecision(4),
        )
      : 0,
    isBest: row.isBest,
  }));

  return (
    <div className="space-y-5">
      {onSelect && (
        <p className="mono text-[10px] text-[var(--bone-faint)]">
          Select any experiment to inspect it in the side panel.
        </p>
      )}

      {/* ------------------------------------------------------------- table */}
      <div className="recess overflow-x-auto">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="border-b hairline">
              {[
                "Experiment",
                "Approach",
                primaryLabel,
                ...secondary.map(pretty),
                `Δ ${primaryLabel}`,
                "Hypothesis",
              ].map(
                (heading) => (
                  <th key={heading} className="label whitespace-nowrap px-3 py-2">
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {comparison.rows.map((row, rowIndex) => (
              <motion.tr
                key={row.id}
                initial={reduced ? false : { opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{
                  duration: 0.32,
                  delay: reduced ? 0 : Math.min(rowIndex * 0.05, 0.4),
                  ease: [0.2, 0.8, 0.3, 1],
                }}
                onClick={() => onSelect?.(row.id)}
                tabIndex={onSelect ? 0 : undefined}
                onKeyDown={(event) => {
                  if (onSelect && (event.key === "Enter" || event.key === " ")) {
                    event.preventDefault();
                    onSelect(row.id);
                  }
                }}
                aria-selected={selectedId === row.id}
                title={onSelect ? "Show this experiment in the side panel" : undefined}
                className={`compare-row border-b hairline last:border-0 ${
                  onSelect ? "cursor-pointer hover:bg-[rgba(111,179,173,0.07)]" : ""
                } ${row.isBest && selectedId !== row.id ? "best-glow" : ""}`}
                style={
                  selectedId === row.id
                    ? {
                        background: "rgba(111,179,173,0.12)",
                        boxShadow: "inset 2px 0 0 var(--teal)",
                      }
                    : row.isBest
                      ? { background: "rgba(143,174,134,0.08)" }
                      : undefined
                }
              >
                <td className="whitespace-nowrap px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <span className="mono text-[11.5px] text-[var(--bone)]">
                      EXP-{String(row.index).padStart(3, "0")}
                    </span>
                    {row.isBaseline && <Badge tone="bone">base</Badge>}
                    {row.isBest && <Badge tone="sage">★</Badge>}
                  </div>
                </td>
                <td className="mono whitespace-nowrap px-3 py-2.5 text-[10.5px] text-[var(--bone-faint)]">
                  {row.approach}
                  <span className="text-[var(--teal)]"> · {row.featureSet}</span>
                </td>
                <td className="mono px-3 py-2.5 text-[12px] text-[var(--sage)]">
                  {fmt(primaryKey, row.metrics[primaryKey])}
                </td>
                {secondary.map((metric) => (
                  <td
                    key={metric}
                    className="mono px-3 py-2.5 text-[11.5px]"
                    style={{
                      color:
                        metric === "optimality_gap_percent" || metric === "false_positive_rate"
                          ? "var(--amber)"
                          : "var(--bone-dim)",
                    }}
                  >
                    {fmt(metric, row.metrics[metric])}
                  </td>
                ))}
                <td
                  className="mono px-3 py-2.5 text-[11.5px]"
                  style={{ color: row.f1Delta >= 0 ? "var(--sage)" : "var(--terracotta)" }}
                >
                  {row.isBaseline ? "—" : `${row.f1Delta >= 0 ? "+" : ""}${row.f1ImprovementPct.toFixed(1)}%`}
                </td>
                <td className="px-3 py-2.5">
                  {row.hypothesisSupported === null ? (
                    <span className="mono text-[10.5px] text-[var(--bone-faint)]">—</span>
                  ) : (
                    <Badge tone={row.hypothesisSupported ? "sage" : "terracotta"}>
                      {row.hypothesisSupported ? "supported" : "not supported"}
                    </Badge>
                  )}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ------------------------------------------------------------ charts */}
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="panel p-3.5">
          <h3 className="label engraved mb-3">{primaryLabel} by Experiment</h3>
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={chartData} margin={{ top: 4, right: 6, left: -22, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(151,163,161,0.12)" vertical={false} />
              <XAxis dataKey="name" {...AXIS} />
              <YAxis {...AXIS} />
              <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "rgba(111,179,173,0.07)" }} />
              <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "#97a3a1" }} />
              <Bar
                dataKey={primaryLabel}
                radius={[3, 3, 0, 0]}
                animationDuration={reduced ? 0 : 750}
                animationEasing="ease-out"
              >
                {chartData.map((entry, index) => (
                  <Cell key={index} fill={entry.isBest ? "#8fae86" : "#4a6b63"} />
                ))}
              </Bar>
              {secondary
                .filter((m) => m !== trajectoryKey)
                .map((m, i) => (
                  <Bar
                    key={m}
                    dataKey={pretty(m)}
                    fill={["#6fb3ad", "#8f8ab8"][i % 2]}
                    radius={[3, 3, 0, 0]}
                    animationDuration={reduced ? 0 : 750}
                    animationBegin={reduced ? 0 : 120 + i * 90}
                  />
                ))}
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="panel p-3.5">
          <h3 className="label engraved mb-3">
            {trajectoryKey ? `${pretty(trajectoryKey)} Trajectory` : "Trajectory"}
          </h3>
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={chartData} margin={{ top: 4, right: 6, left: -22, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="rgba(151,163,161,0.12)" vertical={false} />
              <XAxis dataKey="name" {...AXIS} />
              <YAxis {...AXIS} unit="%" />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Line
                type="monotone"
                dataKey="Trajectory"
                stroke="#d9a441"
                strokeWidth={2}
                dot={{ r: 4, fill: "#d9a441", strokeWidth: 0 }}
                activeDot={{ r: 6 }}
                animationDuration={reduced ? 0 : 950}
                animationEasing="ease-out"
              />
            </LineChart>
          </ResponsiveContainer>
          <p className="mono mt-2 text-[10px] text-[var(--bone-faint)]">
            {trajectoryKey === "optimality_gap_percent"
              ? "Lower is better — the gap is how much path quality each speedup costs."
              : "Lower is better — false positives dominate operational cost at realistic attack prevalence."}
          </p>
        </div>
      </div>
    </div>
  );
}
