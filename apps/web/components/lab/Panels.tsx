"use client";

import { useState } from "react";

import { Badge, Button, Empty, Meter, Modal } from "@/components/ui/Instrument";
import { api } from "@/lib/api";
import { exportBestModel, exportReport } from "@/lib/export";
import { baselineOutcome, describeDegeneracy } from "@/lib/metrics";
import type {
  Comparison,
  Decision,
  Hypothesis,
  Paper,
  RunDetail,
} from "@/lib/types";

/* The source viewer is large enough to own its own file; re-exported here
   so callers keep a single import for every lab modal. */
export { CodeViewer } from "@/components/lab/CodeViewer";

/* ------------------------------------------------------------------- why */
export function WhyPanel({
  open,
  onClose,
  decisions,
  hypotheses,
}: {
  open: boolean;
  onClose: () => void;
  decisions: Decision[];
  hypotheses: Hypothesis[];
}) {
  const byId = new Map(hypotheses.map((hypothesis) => [hypothesis.id, hypothesis]));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Why did GENESIS choose this?"
      subtitle="Decision factors and evidence behind every Principal Investigator call"
    >
      {decisions.length === 0 ? (
        <Empty>No decisions recorded yet.</Empty>
      ) : (
        <ol className="space-y-3">
          {[...decisions].reverse().map((decision) => {
            const hypothesis = decision.selected_hypothesis_id
              ? byId.get(decision.selected_hypothesis_id)
              : null;
            return (
              <li key={decision.id} className="panel p-4">
                <div className="mb-2.5 flex items-start justify-between gap-4">
                  <div>
                    <span className="label">Decision #{decision.index + 1}</span>
                    <p className="mt-1 text-[13.5px] leading-snug text-[var(--bone)]">
                      {decision.decision}
                    </p>
                  </div>
                  <div className="w-[110px] shrink-0">
                    <div className="mb-1 flex items-baseline justify-between">
                      <span className="label">Conf</span>
                      <span className="mono text-[11px] text-[var(--iris)]">
                        {Math.round(decision.confidence * 100)}%
                      </span>
                    </div>
                    <Meter value={decision.confidence} tone="iris" />
                  </div>
                </div>

                <span className="label mb-1.5 block">Evidence</span>
                <ul className="space-y-1.5">
                  {decision.evidence.map((item, index) => (
                    <li key={index} className="flex gap-2 text-[12px] leading-snug text-[var(--bone-dim)]">
                      <span className="mono shrink-0 text-[var(--teal)]">·</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Badge tone="bone">Cost: {decision.estimated_cost}</Badge>
                  <Badge tone="teal">Expected value: {decision.expected_value.toFixed(2)}</Badge>
                  {hypothesis && <Badge tone="amber">{hypothesis.approach}</Badge>}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Modal>
  );
}

/* -------------------------------------------------------------- literature */
export function LiteraturePanel({
  open,
  onClose,
  papers,
}: {
  open: boolean;
  onClose: () => void;
  papers: Paper[];
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Literature Discovered"
      subtitle={`${papers.length} papers reviewed by the SCOUT agent`}
    >
      {papers.length === 0 ? (
        <Empty>No literature retrieved yet.</Empty>
      ) : (
        <ul className="space-y-2.5">
          {papers.map((paper) => (
            <li key={paper.id} className="panel p-4">
              <div className="mb-1.5 flex items-start justify-between gap-3">
                <h3 className="text-[13px] leading-snug text-[var(--bone)]">{paper.title}</h3>
                <Badge tone={paper.source === "arxiv" ? "teal" : "amber"}>{paper.source}</Badge>
              </div>
              <p className="mono mb-2 text-[10.5px] text-[var(--bone-faint)]">
                {paper.authors.slice(0, 4).join(", ")}
                {paper.authors.length > 4 ? " et al." : ""}
                {paper.published && ` · ${paper.published}`}
              </p>
              <p className="mb-2 text-[11.5px] leading-snug text-[var(--bone-dim)]">
                {paper.abstract.slice(0, 320)}
                {paper.abstract.length > 320 ? "…" : ""}
              </p>
              <div className="flex items-center justify-between gap-3">
                <div className="flex w-[150px] items-center gap-2">
                  <span className="label">Relevance</span>
                  <Meter value={paper.relevance} tone="teal" height={4} />
                </div>
                {paper.url && (
                  <a
                    href={paper.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mono text-[10.5px] text-[var(--teal)] underline-offset-2 hover:underline"
                  >
                    open ↗
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}

/* --------------------------------------------------------------- injection */
export function InjectHypothesis({
  open,
  onClose,
  runId,
  onInjected,
}: {
  open: boolean;
  onClose: () => void;
  runId: string;
  onInjected: () => void;
}) {
  const [title, setTitle] = useState("");
  const [rationale, setRationale] = useState("");
  const [approach, setApproach] = useState("gradient_boosting");
  const [featureSet, setFeatureSet] = useState("temporal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.injectHypothesis({
        run_id: runId,
        title: title.trim(),
        rationale: rationale.trim(),
        approach,
        feature_set: featureSet,
      });
      setTitle("");
      setRationale("");
      onInjected();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not inject the hypothesis");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Inject a Hypothesis"
      subtitle="GENESIS will prioritise your hypothesis for the next experiment"
      width="max-w-2xl"
    >
      <div className="space-y-4">
        <div>
          <label className="label mb-1.5 block" htmlFor="hypothesis-title">
            Hypothesis
          </label>
          <div className="recess p-1">
            <input
              id="hypothesis-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="e.g. Gradient boosting on temporal features beats random forest"
              className="mono w-full bg-transparent px-3 py-2 text-[12.5px] text-[var(--bone)] outline-none placeholder:text-[var(--bone-faint)]"
            />
          </div>
        </div>

        <div>
          <label className="label mb-1.5 block" htmlFor="hypothesis-rationale">
            Rationale
          </label>
          <div className="recess p-1">
            <textarea
              id="hypothesis-rationale"
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              rows={3}
              placeholder="Why is this worth testing?"
              className="mono w-full resize-none bg-transparent px-3 py-2 text-[12.5px] leading-relaxed text-[var(--bone)] outline-none placeholder:text-[var(--bone-faint)]"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className="label mb-1.5 block">Approach</span>
            <div className="recess p-1">
              <select
                value={approach}
                onChange={(event) => setApproach(event.target.value)}
                className="mono w-full bg-transparent px-2 py-1.5 text-[11.5px] text-[var(--bone)] outline-none"
              >
                {[
                  "isolation_forest",
                  "one_class_svm",
                  "random_forest",
                  "gradient_boosting",
                  "autoencoder",
                  "ensemble_adaptive",
                ].map((option) => (
                  <option key={option} value={option} style={{ background: "#182125" }}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <span className="label mb-1.5 block">Feature Set</span>
            <div className="recess p-1">
              <select
                value={featureSet}
                onChange={(event) => setFeatureSet(event.target.value)}
                className="mono w-full bg-transparent px-2 py-1.5 text-[11.5px] text-[var(--bone)] outline-none"
              >
                <option value="base" style={{ background: "#182125" }}>base</option>
                <option value="temporal" style={{ background: "#182125" }}>temporal</option>
              </select>
            </div>
          </div>
        </div>

        {error && <p className="mono text-[11.5px] text-[var(--terracotta)]">{error}</p>}

        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void submit()} disabled={busy || title.trim().length < 4}>
            {busy ? "Injecting…" : "Inject Hypothesis"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------ final report */
function Stat({
  label,
  value,
  tone = "var(--bone)",
  sub,
}: {
  label: string;
  value: string;
  tone?: string;
  sub?: string;
}) {
  return (
    <div className="readout px-3 py-2.5">
      <div className="label mb-1">{label}</div>
      <div className="mono text-[19px] leading-none" style={{ color: tone }}>
        {value}
      </div>
      {sub && (
        <div className="mono mt-1.5 text-[9.5px] leading-tight text-[var(--bone-faint)]">
          {sub}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-6">
      <div className="mb-2.5 flex items-center gap-3">
        <span className="label engraved">{title}</span>
        <div className="tick-rail h-px flex-1" />
      </div>
      {children}
    </div>
  );
}

export function FinalReport({
  open,
  onClose,
  run,
  comparison,
}: {
  open: boolean;
  onClose: () => void;
  run: RunDetail;
  comparison: Comparison | null;
}) {
  const [exporting, setExporting] = useState<"model" | "report" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const summary = run.final_summary;
  if (!summary) return null;

  const rows = comparison?.rows ?? [];
  const best = comparison?.best ?? null;
  const baseline = comparison?.baseline ?? null;
  const bestMetrics = best?.metrics ?? {};

  // Derived facts about how the run actually went.
  const durationMs =
    run.completed_at && run.created_at
      ? new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()
      : 0;
  const durationLabel =
    durationMs > 0
      ? durationMs >= 60_000
        ? `${Math.floor(durationMs / 60_000)}m ${Math.round((durationMs % 60_000) / 1000)}s`
        : `${Math.round(durationMs / 1000)}s`
      : "—";

  /* A run can succeed mechanically and still have measured nothing; the
     report must not dress that up as a winning configuration. */
  const degeneracy = describeDegeneracy(bestMetrics);
  const outcome = baselineOutcome(rows.length, best?.isBaseline);
  const comparable = outcome !== "no-comparison";
  const baselineHeld = outcome === "baseline-held";

  const totalRepairs = run.experiments.reduce((sum, e) => sum + e.repair_attempts, 0);
  const failedExperiments = run.experiments.filter((e) => e.status === "FAILED").length;
  const supported = rows.filter((r) => r.hypothesisSupported === true).length;
  const injected = run.hypotheses.filter((h) => h.origin === "user").length;
  const computeSeconds = rows.reduce((sum, r) => sum + r.executionTime, 0);
  const arxivPapers = run.papers.filter((p) => p.source === "arxiv").length;

  async function handleExportModel() {
    setExporting("model");
    setExportError(null);
    try {
      await exportBestModel(run, comparison);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Research Complete"
      subtitle={run.question}
      width="max-w-5xl"
    >
      {/* ------------------------------------------------------- headline */}
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3 lg:grid-cols-4">
        <Stat
          label="Best F1"
          value={summary.best_f1 !== null ? summary.best_f1.toFixed(4) : "—"}
          tone="var(--sage)"
          sub={baseline ? `baseline ${(baseline.metrics.f1 ?? 0).toFixed(4)}` : undefined}
        />
        <Stat
          label="Improvement"
          value={
            comparable
              ? `${summary.improvement_pct >= 0 ? "+" : ""}${summary.improvement_pct.toFixed(1)}%`
              : "—"
          }
          tone={
            !comparable
              ? "var(--bone-faint)"
              : summary.improvement_pct >= 0
                ? "var(--sage)"
                : "var(--terracotta)"
          }
          sub={
            !comparable
              ? "nothing to compare against"
              : baselineHeld
                ? "no alternative beat the baseline"
                : "F1 vs baseline"
          }
        />
        <Stat
          label="False Positive Rate"
          value={summary.best_fpr !== null ? `${(summary.best_fpr * 100).toFixed(2)}%` : "—"}
          tone="var(--amber)"
          sub={
            baseline
              ? `baseline ${((baseline.metrics.false_positive_rate ?? 0) * 100).toFixed(2)}%`
              : undefined
          }
        />
        <Stat
          label="FPR Change"
          value={comparable ? `${summary.fpr_change_pct.toFixed(1)}%` : "—"}
          tone={
            !comparable
              ? "var(--bone-faint)"
              : summary.fpr_change_pct < 0
                ? "var(--sage)"
                : "var(--terracotta)"
          }
          sub={
            !comparable
              ? "only the baseline ran"
              : baselineHeld
                ? "baseline was already best"
                : summary.fpr_change_pct < 0
                  ? "fewer false alarms"
                  : "more false alarms"
          }
        />
        <Stat label="Experiments" value={String(summary.experiments_run)} tone="var(--teal)"
          sub={failedExperiments ? `${failedExperiments} failed` : "all succeeded"} />
        <Stat label="Hypotheses" value={String(run.hypotheses.length)} tone="var(--amber)"
          sub={`${supported} supported${injected ? ` · ${injected} yours` : ""}`} />
        <Stat label="Papers" value={String(summary.papers_analysed)} tone="var(--iris)"
          sub={arxivPapers ? `${arxivPapers} from live arXiv` : "curated corpus"} />
        <Stat label="Wall Clock" value={durationLabel} tone="var(--bone-dim)"
          sub={`${computeSeconds.toFixed(1)}s of compute`} />
      </div>

      {/* ------------------------------------------- best experiment detail */}
      {best && (
        <Section
          title={
            degeneracy
              ? "Best Run (No Detections)"
              : baselineHeld
                ? "Baseline Held"
                : "Winning Configuration"
          }
        >
          <div
            className="rounded border px-4 py-3 hairline"
            style={{
              background: degeneracy ? "rgba(196,112,90,0.06)" : "rgba(143,174,134,0.05)",
              borderColor: degeneracy ? "rgba(196,112,90,0.32)" : undefined,
            }}
          >
            <div className="mb-2 flex flex-wrap items-baseline gap-2">
              <span className="text-[14px] text-[var(--bone)]">{best.name}</span>
              {/* Ranking highest among runs that all measured nothing is not a
                  win, and a "supported" verdict on a zero-recall model is the
                  analyst contradicting the arithmetic. */}
              {degeneracy ? (
                <Badge tone="terracotta">{degeneracy.label}</Badge>
              ) : (
                <>
                  <Badge tone="sage">★ best</Badge>
                  {best.hypothesisSupported !== null && (
                    <Badge tone={best.hypothesisSupported ? "sage" : "terracotta"}>
                      {best.hypothesisSupported
                        ? "hypothesis supported"
                        : "hypothesis not supported"}
                    </Badge>
                  )}
                </>
              )}
            </div>

            {degeneracy && (
              <p
                className="mb-2.5 rounded border px-3 py-2 text-[12px] leading-relaxed"
                style={{
                  borderColor: "rgba(196,112,90,0.3)",
                  background: "rgba(196,112,90,0.07)",
                  color: "var(--bone-dim)",
                }}
              >
                {degeneracy.detail}
              </p>
            )}

            {!degeneracy && baselineHeld && (
              <p
                className="mb-2.5 rounded border px-3 py-2 text-[12px] leading-relaxed"
                style={{
                  borderColor: "rgba(217,164,65,0.3)",
                  background: "rgba(217,164,65,0.07)",
                  color: "var(--bone-dim)",
                }}
              >
                The baseline is good enough: {rows.length - 1} alternative
                {rows.length - 1 === 1 ? " was" : "s were"} measured against it on the
                same split and none beat it. That is a result, not a failed run — the
                simplest approach is the one to keep unless a later hypothesis clears it.
              </p>
            )}
            <p className="mono text-[10.5px] text-[var(--bone-faint)]">
              {best.approach} · {best.featureSet} features · {best.thresholdStrategy} threshold ·{" "}
              {best.executionTime.toFixed(1)}s
            </p>

            <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
              {[
                ["Precision", bestMetrics.precision],
                ["Recall", bestMetrics.recall],
                ["Accuracy", bestMetrics.accuracy],
                ["ROC AUC", bestMetrics.roc_auc],
                ["F1", bestMetrics.f1],
              ].map(([label, value]) => (
                <div key={label as string} className="recess px-2.5 py-2">
                  <div className="label !text-[8.5px]">{label as string}</div>
                  <div className="mono mt-1 text-[13px] text-[var(--bone)]">
                    {typeof value === "number" ? value.toFixed(4) : "—"}
                  </div>
                </div>
              ))}
            </div>

            {typeof bestMetrics.true_positives === "number" && (
              <div className="mt-2">
                <span className="label mb-1.5 block">Detection Breakdown</span>
                <div className="recess grid grid-cols-4 gap-px overflow-hidden">
                  {[
                    ["True Positives", bestMetrics.true_positives, "var(--sage)", "attacks caught"],
                    ["False Positives", bestMetrics.false_positives, "var(--terracotta)", "false alarms"],
                    ["False Negatives", bestMetrics.false_negatives, "var(--amber)", "attacks missed"],
                    ["True Negatives", bestMetrics.true_negatives, "var(--bone-dim)", "correctly ignored"],
                  ].map(([label, value, color, note]) => (
                    <div key={label as string} className="px-2.5 py-2 text-center">
                      <div className="mono text-[8.5px] tracking-[0.1em] text-[var(--bone-faint)]">
                        {label as string}
                      </div>
                      <div className="mono text-[16px]" style={{ color: color as string }}>
                        {Math.round(value as number)}
                      </div>
                      <div className="mono text-[8px] text-[var(--bone-faint)]">{note as string}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ------------------------------------------------- recommendation */}
      <Section title="GENESIS Recommendation">
        <div
          className="rounded border px-4 py-3"
          style={{ borderColor: "rgba(143,174,134,0.3)", background: "rgba(143,174,134,0.07)" }}
        >
          <p className="text-[13px] leading-relaxed text-[var(--bone)]">{summary.recommendation}</p>
        </div>
      </Section>

      {summary.what_was_learned.length > 0 && (
        <Section title="What Was Learned">
          <ul className="space-y-1.5">
            {summary.what_was_learned.map((item, index) => (
              <li key={index} className="flex gap-2 text-[12px] leading-snug text-[var(--bone-dim)]">
                <span className="mono shrink-0 text-[var(--sage)]">✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* --------------------------------------------------- what was done */}
      {rows.length > 0 && (
        <Section title="What Was Done">
          <ol className="border-t hairline">
            {rows.map((row) => {
              const experiment = run.experiments.find((e) => e.id === row.id);
              const analysis = experiment?.analysis;
              return (
                <li key={row.id} className="border-b py-3 hairline">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="mono text-[10.5px] text-[var(--teal)]">
                      {String(row.index).padStart(3, "0")}
                    </span>
                    <span className="text-[12.5px] text-[var(--bone)]">{row.name}</span>
                    {row.isBest && <Badge tone="sage">★ best</Badge>}
                    {row.isBaseline && <Badge tone="bone">baseline</Badge>}
                    {row.hypothesisSupported !== null && (
                      <Badge tone={row.hypothesisSupported ? "sage" : "terracotta"}>
                        {row.hypothesisSupported ? "supported" : "not supported"}
                      </Badge>
                    )}
                    {experiment && experiment.repair_attempts > 0 && (
                      <Badge tone="amber">{experiment.repair_attempts}× repaired</Badge>
                    )}
                  </div>
                  <p className="mono mt-1 text-[10px] text-[var(--bone-faint)]">
                    changed: {row.approach} · {row.featureSet} features · {row.thresholdStrategy} threshold
                  </p>
                  <p className="mono mt-1 text-[10.5px] text-[var(--bone-dim)]">
                    measured: F1 {(row.metrics.f1 ?? 0).toFixed(4)} · FPR{" "}
                    {((row.metrics.false_positive_rate ?? 0) * 100).toFixed(2)}% ·{" "}
                    {row.executionTime.toFixed(1)}s
                    {!row.isBaseline && (
                      <span style={{ color: row.f1Delta >= 0 ? "var(--sage)" : "var(--terracotta)" }}>
                        {" "}({row.f1ImprovementPct >= 0 ? "+" : ""}
                        {row.f1ImprovementPct.toFixed(1)}% vs baseline)
                      </span>
                    )}
                  </p>
                  {analysis?.verdict && (
                    <p className="mt-1 text-[11.5px] leading-snug text-[var(--bone-faint)]">
                      {analysis.verdict}
                    </p>
                  )}
                  {analysis?.failure_modes && analysis.failure_modes.length > 0 && (
                    <p className="mt-1 text-[11px] leading-snug text-[var(--terracotta)] opacity-80">
                      {analysis.failure_modes[0]}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </Section>
      )}

      {summary.future_work.length > 0 && (
        <Section title="Further Research">
          <ul className="space-y-1.5">
            {summary.future_work.map((item, index) => (
              <li key={index} className="flex gap-2 text-[12px] leading-snug text-[var(--bone-faint)]">
                <span className="mono shrink-0 text-[var(--teal)]">→</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* ------------------------------------------------------ provenance */}
      <Section title="Provenance">
        <div className="recess grid grid-cols-2 gap-x-6 gap-y-1.5 px-4 py-3 sm:grid-cols-3">
          {[
            ["Reasoning", run.llm_provider],
            ["Execution", `${run.sandbox_backend} sandbox`],
            ["Dataset", "deterministic · seed 42"],
            ["Literature", arxivPapers ? "live arXiv" : "curated corpus"],
            ["Code repairs", totalRepairs ? `${totalRepairs} autonomous` : "none needed"],
            ["Completed", run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"],
          ].map(([label, value]) => (
            <div key={label} className="flex items-baseline justify-between gap-3">
              <span className="mono text-[10px] text-[var(--bone-faint)]">{label}</span>
              <span className="mono text-[10px] text-[var(--bone-dim)]">{value}</span>
            </div>
          ))}
        </div>
        <p className="mono mt-2 text-[10px] leading-relaxed text-[var(--bone-faint)]">
          Every metric above was computed by code that actually executed in the
          sandbox. No number in this report was written by a language model.
        </p>
      </Section>

      {/* ---------------------------------------------------------- export */}
      <Section title="Export">
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="primary"
            onClick={() => void handleExportModel()}
            disabled={exporting !== null || rows.length === 0}
          >
            {exporting === "model" ? "Exporting…" : "Export Best Model"}
          </Button>
          <Button
            onClick={() => {
              setExporting("report");
              try {
                exportReport(run, comparison);
              } finally {
                setExporting(null);
              }
            }}
            disabled={exporting !== null}
          >
            Export Report
          </Button>
        </div>
        <p className="mono mt-2.5 max-w-[70ch] text-[10px] leading-relaxed text-[var(--bone-faint)]">
          There is no pickled model to ship — experiments run in a throwaway sandbox
          and only their metrics are kept. The export is the exact seeded program
          that produced the winning result, so it can be reproduced rather than
          trusted.
        </p>
        {exportError && (
          <p className="mono mt-2 text-[11px] text-[var(--terracotta)]">{exportError}</p>
        )}
      </Section>
    </Modal>
  );
}
