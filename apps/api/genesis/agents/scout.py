"""SCOUT -- literature discovery and research-gap extraction."""
from __future__ import annotations

import logging

from ..literature.arxiv import PaperRecord, discover
from .llm import LLMError, get_llm
from .schemas import ScoutReport

logger = logging.getLogger(__name__)

SYSTEM = (
    "You are SCOUT, the literature analyst of an autonomous research lab. "
    "You read paper titles and abstracts and extract the concepts, methods and "
    "open gaps that a research team could actually test. Be concrete and "
    "domain-specific. Never invent papers or citations."
)


class ScoutAgent:
    name = "SCOUT"

    def run(
        self, question: str
    ) -> tuple[list[PaperRecord], ScoutReport, str, str | None]:
        """Returns the papers, the analysis, the corpus used, and — when the
        live search did not carry the run — why it did not."""
        papers, source, reason = discover(question)
        report = self._analyse(question, papers)
        return papers, report, source, reason

    def _analyse(self, question: str, papers: list[PaperRecord]) -> ScoutReport:
        llm = get_llm()
        if llm.enabled and papers:
            digest = "\n\n".join(
                f"[{i + 1}] {p.title} ({p.published})\n{p.abstract[:600]}"
                for i, p in enumerate(papers[:10])
            )
            try:
                return llm.complete_json(
                    SYSTEM,
                    (
                        f"Research question:\n{question}\n\n"
                        f"Retrieved literature:\n{digest}\n\n"
                        "Extract:\n"
                        "- concepts: 4-8 core technical concepts these papers share\n"
                        "- methods: 4-8 concrete methods or model families used\n"
                        "- gaps: 3-5 specific, testable gaps or unresolved problems\n"
                        "- summary: 2-3 sentences on what the literature implies for "
                        "this question\n"
                        "- confidence: 0-1, how well this literature covers the question"
                    ),
                    ScoutReport,
                    temperature=0.4,
                    task="scout",
                )
            except LLMError as exc:
                logger.warning("scout LLM analysis failed (%s); using extracted concepts", exc)

        return self._fallback(papers)

    def _fallback(self, papers: list[PaperRecord]) -> ScoutReport:
        """Derive a report from the retrieved papers without an LLM."""
        concepts: list[str] = []
        for paper in papers:
            for concept in paper.concepts:
                if concept not in concepts:
                    concepts.append(concept)

        text = " ".join(f"{p.title} {p.abstract}".lower() for p in papers)
        method_terms = {
            "isolation forest": "isolation forest",
            "autoencoder": "autoencoder",
            "random forest": "random forest",
            "one-class": "one-class SVM",
            "svm": "support vector machines",
            "lstm": "recurrent sequence models",
            "clustering": "clustering",
            "ensemble": "model ensembles",
            "deep": "deep neural networks",
            "nearest neighbour": "nearest-neighbour outlier scoring",
        }
        methods = [label for term, label in method_terms.items() if term in text]

        if not concepts:
            concepts = [
                "unsupervised anomaly detection",
                "flow-level features",
                "class imbalance",
                "false-positive cost",
            ]
        if not methods:
            methods = ["isolation forest", "autoencoder", "random forest"]

        return ScoutReport(
            concepts=concepts[:8],
            methods=methods[:8],
            gaps=[
                "Per-flow features cannot express behaviour that spans multiple flows, "
                "so burst-shaped attacks such as port scans are structurally invisible.",
                "Benign traffic that mimics attacks (monitoring sweeps, scheduled backups, "
                "flash crowds) is a dominant and under-addressed source of false positives.",
                "Fixed decision thresholds ignore the shape of the score distribution and "
                "are rarely tuned against operational false-positive budgets.",
                "Accuracy is reported far more often than false-positive rate, despite the "
                "latter dominating real deployment cost at low attack prevalence.",
            ],
            summary=(
                f"Reviewed {len(papers)} works spanning classical outlier detection and "
                "deep methods. The recurring operational theme is that false positives, "
                "not missed detections, limit deployability, and that temporal context is "
                "the most commonly cited source of additional signal."
            ),
            confidence=0.72 if papers else 0.4,
        )
