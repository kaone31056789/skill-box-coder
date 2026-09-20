"use client";

/**
 * The one-glance answer to "is this run working?".
 *
 * The comparison table has every number, but it lives behind a tab. This
 * sits inside Run Status so it costs the column no extra panel chrome —
 * vertical space here is contested, and the agent rail below it is the
 * signal people actually watch.
 */
import { AnimatePresence, motion } from "motion/react";

import { AnimatedNumber, Sparkline } from "@/components/ui/Motion";
import type { Comparison } from "@/lib/types";

function pretty(name: string): string {
  return name
    .replace(/_percent$/, " %")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bF1\b/i, "F1")
    .replace(/\bFpr\b/i, "FPR")
    .replace(/\bAuc\b/i, "AUC");
}

export function RunVitals({ comparison }: { comparison: Comparison | null }) {
  const rows = comparison?.rows ?? [];
  if (rows.length === 0) return null;

  const primaryKey = comparison?.primaryMetric ?? "f1";
  const minimising = comparison?.metricDirection === "minimize";
  const series = rows.map((row) => row.metrics[primaryKey] ?? 0);
  const best = comparison?.best ?? null;
  const baseline = comparison?.baseline ?? null;

  const bestValue = best?.metrics[primaryKey] ?? Math.max(...series);
  const baselineValue = baseline?.metrics[primaryKey] ?? null;
  const improvement = best?.f1ImprovementPct ?? 0;
  const improved = minimising ? improvement <= 0 : improvement >= 0;
  const tone = improved ? "var(--sage)" : "var(--terracotta)";

  const computeSeconds = rows.reduce((total, row) => total + row.executionTime, 0);
  const supported = rows.filter((row) => row.hypothesisSupported === true).length;
  const tested = rows.filter((row) => row.hypothesisSupported !== null).length;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="label engraved">Vitals</span>
        <div className="tick-rail h-px flex-1" />
      </div>

      {/* Headline reading and the shape of the run, on one line. */}
      <div className="vitals">
        <div className="min-w-0">
          <div className="label mb-1 truncate">Best {pretty(primaryKey)}</div>
          <AnimatedNumber
            value={bestValue}
            format={(value) => (Math.abs(value) >= 100 ? value.toFixed(1) : value.toFixed(4))}
            className="vitals-figure"
            style={{ color: tone }}
          />
        </div>
        <Sparkline values={series} width={86} height={30} color={tone} />
      </div>

      <div className="mt-1.5 flex items-baseline justify-between gap-2">
        <span className="mono text-[9.5px] text-[var(--bone-faint)]">
          {baselineValue !== null ? `baseline ${baselineValue.toFixed(4)}` : "no baseline yet"}
        </span>
        <AnimatePresence mode="wait" initial={false}>
          {baseline && rows.length > 1 && (
            <motion.span
              key={improvement.toFixed(2)}
              className="mono shrink-0 text-[11px]"
              style={{ color: tone }}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.24 }}
            >
              {improvement >= 0 ? "+" : ""}
              {improvement.toFixed(1)}%
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      {/* Everything secondary compressed into a single engraved line. */}
      <div className="mono mt-1.5 flex items-baseline gap-2 text-[9.5px] text-[var(--bone-faint)]">
        {tested > 0 && (
          <span>
            {supported}/{tested} supported
          </span>
        )}
        <span className="ml-auto">{computeSeconds.toFixed(1)}s sandbox</span>
      </div>
    </div>
  );
}
