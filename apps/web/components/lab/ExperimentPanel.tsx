"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

import { Badge, Empty, Meter, Readout } from "@/components/ui/Instrument";
import { AnimatedNumber, Reveal, Stagger, StaggerItem } from "@/components/ui/Motion";
import type { ComparisonRow, Decision, Experiment, RunDetail } from "@/lib/types";

const COUNT_METRICS = new Set([
  "true_positives",
  "false_positives",
  "false_negatives",
  "true_negatives",
  "n_test",
  "n_train",
]);

/** "avg_path_length" -> "Avg Path Length" */
function prettyMetric(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\bF1\b/i, "F1")
    .replace(/\bFpr\b/i, "FPR")
    .replace(/\bRmse\b/i, "RMSE")
    .replace(/\bAuc\b/i, "AUC");
}

/** Rates render as percentages; everything else keeps significant digits. */
function formatMetric(name: string, value: number): string {
  if (name.includes("rate") || name === "fpr") return (value * 100).toFixed(2);
  if (Math.abs(value) >= 1000 || (Math.abs(value) < 0.001 && value !== 0)) {
    return value.toPrecision(4);
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}

function statusTone(status: string): "sage" | "terracotta" | "teal" | "amber" {
  if (status === "SUCCEEDED") return "sage";
  if (status === "FAILED" || status === "ABANDONED") return "terracotta";
  if (status === "RUNNING") return "teal";
  return "amber";
}

/**
 * Live stdout from the running sandbox, tailing as lines arrive.
 *
 * Only the newest line animates in — replaying the whole buffer on every
 * append would turn a fast-printing experiment into a strobe.
 */
function LiveConsole({ lines }: { lines: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines]);

  return (
    <div className="mt-3">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="spinner" aria-hidden />
        <span className="label !text-[var(--teal)]">Sandbox Output</span>
        <span className="mono ml-auto text-[9.5px] text-[var(--bone-faint)]">
          <AnimatedNumber value={lines.length} format={(v) => String(Math.round(v))} flash={false} />{" "}
          lines
        </span>
      </div>
      <div
        ref={ref}
        className="recess max-h-[180px] overflow-y-auto px-2.5 py-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {lines.map((line, index) => {
          const newest = index === lines.length - 1;
          return (
            <motion.div
              key={index}
              className="mono whitespace-pre-wrap break-words text-[10.5px] leading-relaxed text-[var(--sage)]"
              initial={newest && !reduced ? { opacity: 0, x: -5 } : false}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
            >
              {line}
            </motion.div>
          );
        })}
        {!reduced && <span className="console-caret" aria-hidden />}
      </div>
    </div>
  );
}

export function ExperimentPanel({
  run,
  experiment,
  row,
  decision,
  output = [],
}: {
  run: RunDetail;
  experiment: Experiment | null;
  row: ComparisonRow | null;
  decision: Decision | null;
  output?: string[];
}) {
  if (!experiment) {
    return (
      <Empty>
        No experiment yet. GENESIS designs its first experiment after reviewing the
        literature.
      </Empty>
    );
  }

  const metrics = row?.metrics ?? {};
  const primaryName = row?.primaryMetric ?? (("f1" in metrics) ? "f1" : Object.keys(metrics)[0] ?? "f1");
  // Counts and the headline metric are shown separately; the rest go in the grid.
  const secondaryMetrics = Object.entries(metrics)
    .filter(
      ([name]) =>
        name !== primaryName &&
        name !== "false_positive_rate" &&
        !COUNT_METRICS.has(name),
    )
    .slice(0, 6);
  const analysis = experiment.analysis;
  const isBest = experiment.id === run.best_experiment_id;
  const hasMetrics = Object.keys(metrics).length > 0;

  return (
    /* Keyed on the experiment so switching selection crossfades the whole
       panel rather than mutating a dozen values in place. */
    <div className="h-full overflow-y-auto p-3.5">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={experiment.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.22, ease: [0.2, 0.8, 0.3, 1] }}
        >
          {/* --------------------------------------------- experiment header */}
          <div className="mb-3">
            <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
              <Badge tone={statusTone(experiment.status)} animated>
                {experiment.status}
              </Badge>
              {experiment.is_baseline && <Badge tone="bone">Baseline</Badge>}
              {isBest && (
                <motion.span
                  initial={{ scale: 0.7, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: "spring", stiffness: 380, damping: 18, delay: 0.1 }}
                >
                  <Badge tone="sage">★ Best</Badge>
                </motion.span>
              )}
              {experiment.repair_attempts > 0 && (
                <Badge tone="amber">{experiment.repair_attempts}× repaired</Badge>
              )}
            </div>
            <h3 className="text-[13px] leading-snug text-[var(--bone)]">{experiment.name}</h3>
            <p className="mono mt-1 text-[10px] text-[var(--bone-faint)]">
              {experiment.design.approach} · {experiment.design.feature_set} features ·{" "}
              {experiment.design.threshold_strategy} threshold
            </p>
          </div>

          {/* -------------------------------------------------------- metrics */}
          {hasMetrics ? (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                <Readout
                  label={prettyMetric(primaryName)}
                  value={metrics[primaryName] ?? 0}
                  format={(value) => formatMetric(primaryName, value)}
                  tone="sage"
                  size="md"
                  delta={
                    row && !row.isBaseline
                      ? {
                          value: `${row.f1Delta >= 0 ? "+" : ""}${row.f1Delta.toFixed(3)}`,
                          good: row.f1Delta >= 0,
                        }
                      : null
                  }
                />
                {"false_positive_rate" in metrics ? (
                  <Readout
                    label="False Positive Rate"
                    value={(metrics.false_positive_rate ?? 0) * 100}
                    format={(value) => value.toFixed(2)}
                    unit="%"
                    tone={(metrics.false_positive_rate ?? 0) < 0.02 ? "sage" : "amber"}
                    delta={
                      row && !row.isBaseline
                        ? {
                            value: `${row.fprChangePct >= 0 ? "+" : ""}${row.fprChangePct.toFixed(0)}%`,
                            good: row.fprChangePct < 0,
                          }
                        : null
                    }
                  />
                ) : (
                  <Readout
                    label="Exec Time"
                    value={row?.executionTime ?? 0}
                    format={(value) => value.toFixed(2)}
                    unit="s"
                    size="md"
                  />
                )}
              </div>

              {/* Whatever else this experiment measured, in its own terms. */}
              <Stagger className="mt-1.5 grid grid-cols-2 gap-1.5" delay={0.08}>
                {secondaryMetrics.map(([name, value]) => (
                  <StaggerItem key={name}>
                    <Readout
                      label={prettyMetric(name)}
                      value={value}
                      format={(current) => formatMetric(name, current)}
                      size="sm"
                      tone="teal"
                    />
                  </StaggerItem>
                ))}
              </Stagger>

              {typeof metrics.true_positives === "number" && (
                <Reveal delay={0.12} className="mt-1.5">
                  <div className="recess grid grid-cols-4 gap-px overflow-hidden">
                    {[
                      ["TP", metrics.true_positives, "var(--sage)"],
                      ["FP", metrics.false_positives, "var(--terracotta)"],
                      ["FN", metrics.false_negatives, "var(--amber)"],
                      ["TN", metrics.true_negatives, "var(--bone-dim)"],
                    ].map(([key, value, color]) => (
                      <div key={key as string} className="px-2 py-1.5 text-center">
                        <div className="mono text-[8.5px] tracking-[0.12em] text-[var(--bone-faint)]">
                          {key as string}
                        </div>
                        <AnimatedNumber
                          value={(value as number) ?? 0}
                          format={(current) => String(Math.round(current))}
                          className="mono block text-[13px]"
                          style={{ color: color as string }}
                        />
                      </div>
                    ))}
                  </div>
                </Reveal>
              )}
            </>
          ) : (
            <div className="recess px-3 py-4 text-center">
              <p className="mono text-[10.5px] text-[var(--bone-faint)]">
                {experiment.status === "RUNNING" ? "Executing in sandbox…" : "Awaiting execution"}
              </p>
              {experiment.status === "RUNNING" && <div className="activity-bar mt-2.5" />}
            </div>
          )}

          {output.length > 0 && <LiveConsole lines={output} />}

          {/* ------------------------------------------------------- analysis */}
          {analysis && (
            <Reveal delay={0.06} className="mt-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="label engraved">Analyst Verdict</span>
                <div className="tick-rail h-px flex-1" />
              </div>
              <motion.div
                className="rounded border px-3 py-2.5"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ type: "spring", stiffness: 260, damping: 26 }}
                style={{
                  borderColor: analysis.hypothesis_supported
                    ? "rgba(143,174,134,0.32)"
                    : "rgba(196,112,90,0.32)",
                  background: analysis.hypothesis_supported
                    ? "rgba(143,174,134,0.07)"
                    : "rgba(196,112,90,0.07)",
                }}
              >
                <div
                  className="mono mb-1.5 text-[10px] uppercase tracking-[0.13em]"
                  style={{
                    color: analysis.hypothesis_supported ? "var(--sage)" : "var(--terracotta)",
                  }}
                >
                  Hypothesis {analysis.hypothesis_supported ? "Supported" : "Not Supported"}
                </div>
                <p className="text-[12px] leading-snug text-[var(--bone-dim)]">{analysis.verdict}</p>
              </motion.div>

              {analysis.key_findings.length > 0 && (
                <Stagger className="mt-2.5 space-y-1.5" delay={0.12}>
                  {analysis.key_findings.slice(0, 4).map((finding, index) => (
                    <StaggerItem
                      key={index}
                      className="flex gap-2 text-[11.5px] leading-snug text-[var(--bone-dim)]"
                    >
                      <span className="mono shrink-0 text-[var(--teal)]">→</span>
                      <span>{finding}</span>
                    </StaggerItem>
                  ))}
                </Stagger>
              )}

              {analysis.failure_modes.length > 0 && (
                <div className="mt-3">
                  <span className="label mb-1.5 block">Failure Modes</span>
                  <Stagger className="space-y-1.5">
                    {analysis.failure_modes.map((mode, index) => (
                      <StaggerItem
                        key={index}
                        className="flex gap-2 text-[11.5px] leading-snug text-[var(--bone-faint)]"
                      >
                        <span className="mono shrink-0 text-[var(--terracotta)]">✗</span>
                        <span>{mode}</span>
                      </StaggerItem>
                    ))}
                  </Stagger>
                </div>
              )}
            </Reveal>
          )}

          {/* ---------------------------------------------------- PI decision */}
          {decision && (
            <Reveal delay={0.1} className="mt-4">
              <div className="mb-2 flex items-center gap-2">
                <span className="label engraved">PI Decision</span>
                <div className="tick-rail h-px flex-1" />
              </div>
              <p className="text-[12px] leading-snug text-[var(--bone)]">{decision.decision}</p>

              <div className="mt-2.5">
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="label">Confidence</span>
                  <AnimatedNumber
                    value={decision.confidence * 100}
                    format={(value) => `${Math.round(value)}%`}
                    className="mono text-[11px] text-[var(--iris)]"
                  />
                </div>
                <Meter value={decision.confidence} tone="iris" />
              </div>

              <div className="mt-2 flex gap-1.5">
                <Badge tone="bone">Cost: {decision.estimated_cost}</Badge>
                <Badge tone="teal">EV: {decision.expected_value.toFixed(2)}</Badge>
              </div>
            </Reveal>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
