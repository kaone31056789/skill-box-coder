import { api } from "./api";
import type { Comparison, RunDetail } from "./types";

function download(filename: string, content: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoke on the next tick; revoking synchronously can cancel the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48);
}

/**
 * Export the winning experiment as a runnable Python file.
 *
 * There is no pickled model to ship: experiments run in a throwaway sandbox
 * and only their metrics are persisted. What is exported is better than a
 * pickle anyway — the exact seeded program that produced the result, so anyone
 * can reproduce it rather than trust it.
 */
export async function exportBestModel(run: RunDetail, comparison: Comparison | null): Promise<void> {
  const best = comparison?.best;
  if (!best) throw new Error("No successful experiment to export yet.");

  const { code } = await api.experimentCode(best.id);
  const metrics = Object.entries(best.metrics)
    .map(([key, value]) => `#   ${key.padEnd(22)} ${value}`)
    .join("\n");

  const header = `#!/usr/bin/env python3
# ============================================================================
# GENESIS — best experiment
#
# Research question:
#   ${run.question}
#
# Winning configuration: ${best.name}
#   approach            ${best.approach}
#   feature set         ${best.featureSet}
#   threshold strategy  ${best.thresholdStrategy}
#
# MEASURED results (produced by executing this exact file in the sandbox):
${metrics}
#   execution_time         ${best.executionTime.toFixed(2)}s
#
# Improvement over baseline: ${best.f1ImprovementPct >= 0 ? "+" : ""}${best.f1ImprovementPct.toFixed(1)}% F1
# Hypothesis: ${best.hypothesisSupported === null ? "n/a" : best.hypothesisSupported ? "SUPPORTED" : "NOT SUPPORTED"}
#
# Reproducing:
#   pip install numpy scipy scikit-learn
#   python ${slug(best.name)}.py     # writes result.json
#
# Everything is seeded (random_state=42), so a re-run reproduces the numbers
# above. Reasoning by ${run.llm_provider}; executed in the ${run.sandbox_backend} sandbox.
# Exported ${new Date().toISOString()}
# ============================================================================

`;

  download(`${slug(best.name) || "genesis-best-experiment"}.py`, header + code, "text/x-python");
}

/** Export the full research record as a Markdown report. */
export function exportReport(run: RunDetail, comparison: Comparison | null): void {
  const summary = run.final_summary;
  const rows = comparison?.rows ?? [];

  const table = rows.length
    ? [
        "| # | Experiment | Approach | Features | F1 | Precision | Recall | FPR | Δ F1 | Time | Hypothesis |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        ...rows.map((r) => {
          const m = r.metrics;
          return `| ${String(r.index).padStart(3, "0")} | ${r.name}${r.isBest ? " ★" : ""} | ${r.approach} | ${r.featureSet} | ${(m.f1 ?? 0).toFixed(4)} | ${(m.precision ?? 0).toFixed(4)} | ${(m.recall ?? 0).toFixed(4)} | ${((m.false_positive_rate ?? 0) * 100).toFixed(2)}% | ${r.isBaseline ? "—" : `${r.f1ImprovementPct >= 0 ? "+" : ""}${r.f1ImprovementPct.toFixed(1)}%`} | ${r.executionTime.toFixed(1)}s | ${r.hypothesisSupported === null ? "—" : r.hypothesisSupported ? "supported" : "not supported"} |`;
        }),
      ].join("\n")
    : "_No experiments completed._";

  const decisions = run.decisions
    .map(
      (d, i) =>
        `### Decision ${i + 1} — confidence ${Math.round(d.confidence * 100)}%\n\n` +
        `**${d.decision}**\n\n` +
        d.evidence.map((e) => `- ${e}`).join("\n") +
        `\n\n_Estimated cost: ${d.estimated_cost} · expected value: ${d.expected_value.toFixed(2)}_`,
    )
    .join("\n\n");

  const journal = rows
    .map((r) => {
      const experiment = run.experiments.find((e) => e.id === r.id);
      const analysis = experiment?.analysis;
      return (
        `### ${String(r.index).padStart(3, "0")} · ${r.name}\n\n` +
        `- **Changed:** ${r.approach} on the \`${r.featureSet}\` feature set, ${r.thresholdStrategy} threshold\n` +
        `- **Measured:** F1 ${(r.metrics.f1 ?? 0).toFixed(4)}, FPR ${((r.metrics.false_positive_rate ?? 0) * 100).toFixed(2)}%, ${r.executionTime.toFixed(1)}s\n` +
        `- **Verdict:** ${analysis?.verdict ?? "—"}\n` +
        (analysis?.failure_modes?.length
          ? `- **Failure modes:** ${analysis.failure_modes.join("; ")}\n`
          : "")
      );
    })
    .join("\n");

  const report = `# GENESIS Research Report

**Question:** ${run.question}

- Completed: ${run.completed_at ?? "in progress"}
- Experiments run: ${summary?.experiments_run ?? rows.length}
- Papers analysed: ${summary?.papers_analysed ?? run.papers.length}
- Reasoning: ${run.llm_provider}
- Execution: ${run.sandbox_backend} sandbox

> Every metric below was computed by code that actually executed. No number in
> this report was written by a language model.

## Result

${
  summary
    ? `**Best configuration:** ${summary.best_experiment_name ?? "—"}\n\n` +
      `- Best F1: **${summary.best_f1?.toFixed(4) ?? "—"}**\n` +
      `- Improvement over baseline: **${summary.improvement_pct >= 0 ? "+" : ""}${summary.improvement_pct.toFixed(1)}%**\n` +
      `- False-positive rate: **${summary.best_fpr !== null ? `${(summary.best_fpr * 100).toFixed(2)}%` : "—"}** (${summary.fpr_change_pct.toFixed(1)}% vs baseline)\n\n` +
      `### Recommendation\n\n${summary.recommendation}\n`
    : "_Run not finished._"
}

${summary?.what_was_learned?.length ? `### What was learned\n\n${summary.what_was_learned.map((x) => `- ${x}`).join("\n")}\n` : ""}
${summary?.future_work?.length ? `### Further research\n\n${summary.future_work.map((x) => `- ${x}`).join("\n")}\n` : ""}

## What was done

${journal || "_No experiments completed._"}

## Experiment comparison

${table}

## Decisions

${decisions || "_No decisions recorded._"}

## Literature reviewed

${run.papers.map((p) => `- ${p.title}${p.published ? ` (${p.published})` : ""} — ${p.source}${p.url ? ` · ${p.url}` : ""}`).join("\n") || "_None._"}

---
_Generated by GENESIS · ${new Date().toISOString()}_
`;

  download(`genesis-report-${slug(run.question) || run.id.slice(0, 8)}.md`, report, "text/markdown");
}
