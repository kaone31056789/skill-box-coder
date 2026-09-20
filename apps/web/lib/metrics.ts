/**
 * Reading a result for what it actually is.
 *
 * A classifier that labels nothing as an anomaly still "succeeds": the code
 * runs, the sandbox exits 0, and every metric is a real number. But precision,
 * recall and F1 are all zero, and calling that run the best result — or its
 * hypothesis supported — tells the operator the opposite of the truth. These
 * checks are arithmetic on the measurements, so they hold regardless of what
 * the analyst agent concluded.
 */

export interface Degeneracy {
  /** Short label for a badge. */
  label: string;
  /** One paragraph explaining what the numbers mean, in plain terms. */
  detail: string;
}

/** Non-null when the result is measured but carries no detection signal. */
export function describeDegeneracy(
  metrics: Record<string, number> | undefined,
): Degeneracy | null {
  if (!metrics || Object.keys(metrics).length === 0) return null;

  const { f1, recall, precision, roc_auc: rocAuc } = metrics;
  const tp = metrics.true_positives;
  const fp = metrics.false_positives;

  const countsSayNothingFlagged = tp === 0 && fp === 0;
  const scoresSayNothingFound = f1 === 0 && recall === 0;

  if (countsSayNothingFlagged || scoresSayNothingFound) {
    /* ROC AUC is threshold-free: if it is well above chance, the model ranks
       anomalies correctly and only the cut-off is wrong. That is a very
       different fix from "these features do not work". */
    const ranksCorrectly = typeof rocAuc === "number" && rocAuc > 0.6;
    return {
      label: "no detections",
      detail: ranksCorrectly
        ? `This model flagged nothing as an anomaly, so precision, recall and F1 are all zero. ` +
          `Its scores still separate anomalies from normal traffic (ROC AUC ${rocAuc.toFixed(3)}), ` +
          `so the decision threshold is misplaced rather than the features being uninformative. ` +
          `Nothing can be concluded about the hypothesis until that is fixed.`
        : `This model flagged nothing as an anomaly, so precision, recall and F1 are all zero. ` +
          `No conclusion about the hypothesis can be drawn from this run.`,
    };
  }

  if (precision === 0 && typeof recall === "number" && recall > 0) {
    return {
      label: "no true positives",
      detail:
        "Everything this model flagged was a false alarm: precision is zero. " +
        "The result is measured, but it carries no usable detection signal.",
    };
  }

  return null;
}

/**
 * What the run actually established about its baseline.
 *
 * Three outcomes that a single "+0.0% improvement" figure cannot tell apart:
 * nothing was compared, alternatives were compared and lost, or an alternative
 * won. The middle case is a real result — "the simple approach is good enough"
 * — and reads as a failure only because the report has no words for it.
 */
export type BaselineOutcome = "no-comparison" | "baseline-held" | "improved";

export function baselineOutcome(
  rowCount: number,
  bestIsBaseline: boolean | undefined,
): BaselineOutcome {
  if (rowCount <= 1) return "no-comparison";
  return bestIsBaseline === true ? "baseline-held" : "improved";
}
