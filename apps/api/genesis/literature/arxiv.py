"""Literature discovery: live arXiv search with a curated offline fallback.

Demo reliability matters more than live data here. If arXiv is slow, rate
limited, or blocked, the Scout falls back to a curated corpus of real,
well-known papers in the domain and clearly labels the source as ``curated``
so the UI never implies a live search happened when it did not.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

from ..config import get_settings

logger = logging.getLogger(__name__)

# Why the most recent live search came back empty, or None if it did not.
_last_failure: str | None = None

_ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"

_STOPWORDS = {
    "can", "we", "the", "a", "an", "of", "to", "in", "for", "and", "or", "with",
    "while", "how", "what", "does", "do", "is", "are", "on", "by", "using", "use",
    "improve", "reduce", "better", "best", "more", "less", "it", "that", "this",
    # Interrogatives and filler. Left in, these outranked the actual subject:
    # a question about distribution shift searched arXiv for "which" and
    # "remain" and came back with papers on model interpretability.
    "which", "when", "where", "why", "who", "whose", "whom", "remain", "remains",
    "most", "least", "over", "under", "between", "produce", "produces", "give",
    "gives", "make", "makes", "have", "has", "been", "being", "be", "will",
    "would", "should", "could", "may", "might", "must", "than", "then", "there",
    "their", "them", "they", "some", "any", "all", "each", "such", "about",
    "significantly", "effectively", "approach", "approaches", "method", "methods",
}


@dataclass
class PaperRecord:
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    url: str = ""
    published: str = ""
    source: str = "arxiv"
    relevance: float = 0.5
    concepts: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Curated fallback corpus -- real papers, summarised in our own words.
# --------------------------------------------------------------------------
CURATED_CORPUS: list[PaperRecord] = [
    PaperRecord(
        title="Isolation Forest",
        authors=["Fei Tony Liu", "Kai Ming Ting", "Zhi-Hua Zhou"],
        abstract=(
            "Introduces isolation-based anomaly detection: rather than profiling normal "
            "points, random trees isolate observations, and anomalies are isolated in "
            "fewer splits. Linear time complexity and low memory, which made it a "
            "standard unsupervised baseline."
        ),
        url="https://ieeexplore.ieee.org/document/4781136",
        published="2008",
        source="curated",
        relevance=0.94,
        concepts=["isolation forest", "unsupervised", "tree ensemble", "baseline"],
    ),
    PaperRecord(
        title=(
            "Outside the Closed World: On Using Machine Learning for Network "
            "Intrusion Detection"
        ),
        authors=["Robin Sommer", "Vern Paxson"],
        abstract=(
            "Argues that machine learning underperforms in intrusion detection relative "
            "to other domains, because of the enormous cost asymmetry of false positives, "
            "the base-rate fallacy at realistic attack prevalence, and the lack of stable "
            "notions of 'normal' traffic. Directly motivates optimising for false-positive "
            "rate rather than accuracy."
        ),
        url="https://ieeexplore.ieee.org/document/5504793",
        published="2010",
        source="curated",
        relevance=0.97,
        concepts=["false positives", "base-rate fallacy", "evaluation", "intrusion detection"],
    ),
    PaperRecord(
        title="Kitsune: An Ensemble of Autoencoders for Online Network Intrusion Detection",
        authors=["Yisroel Mirsky", "Tomer Doitshman", "Yuval Elovici", "Asaf Shabtai"],
        abstract=(
            "An online, unsupervised NIDS built from an ensemble of small autoencoders over "
            "incrementally maintained damped-window traffic statistics. Demonstrates that "
            "cheap streaming temporal features carry much of the detection signal."
        ),
        url="https://arxiv.org/abs/1802.09089",
        published="2018",
        source="curated",
        relevance=0.93,
        concepts=["autoencoder", "ensemble", "temporal features", "online detection"],
    ),
    PaperRecord(
        title="Anomaly Detection: A Survey",
        authors=["Varun Chandola", "Arindam Banerjee", "Vipin Kumar"],
        abstract=(
            "Comprehensive survey organising anomaly detection by technique family "
            "(classification, clustering, nearest neighbour, statistical, spectral) and by "
            "application domain, including intrusion detection. Emphasises that the choice "
            "of what counts as an anomaly is domain-specific."
        ),
        url="https://dl.acm.org/doi/10.1145/1541880.1541882",
        published="2009",
        source="curated",
        relevance=0.88,
        concepts=["survey", "taxonomy", "statistical methods", "clustering"],
    ),
    PaperRecord(
        title=(
            "Toward Generating a New Intrusion Detection Dataset and Intrusion "
            "Traffic Characterization (CICIDS2017)"
        ),
        authors=["Iman Sharafaldin", "Arash Habibi Lashkari", "Ali A. Ghorbani"],
        abstract=(
            "Critiques older IDS benchmarks and introduces a labelled dataset built from "
            "realistic background traffic plus staged attacks, with flow-level features "
            "extracted over time windows. Establishes the flow-feature conventions widely "
            "used in later work."
        ),
        url="https://www.scitepress.org/Link.aspx?doi=10.5220/0006639801080116",
        published="2018",
        source="curated",
        relevance=0.9,
        concepts=["dataset", "flow features", "benchmark", "labelled traffic"],
    ),
    PaperRecord(
        title="Deep Learning for Anomaly Detection: A Survey",
        authors=["Raghavendra Chalapathy", "Sanjay Chawla"],
        abstract=(
            "Surveys deep anomaly detection across supervised, semi-supervised and "
            "unsupervised settings, covering autoencoders, GANs and hybrid models, and "
            "discusses when deep methods do and do not beat classical baselines."
        ),
        url="https://arxiv.org/abs/1901.03407",
        published="2019",
        source="curated",
        relevance=0.85,
        concepts=["deep learning", "autoencoder", "survey", "representation learning"],
    ),
    PaperRecord(
        title="USAD: UnSupervised Anomaly Detection on Multivariate Time Series",
        authors=["Julien Audibert", "Pietro Michiardi", "Frédéric Guyard", "Sébastien Marti", "Maria A. Zuluaga"],
        abstract=(
            "Combines an autoencoder with adversarial training to sharpen the boundary "
            "around normal behaviour in multivariate time series, targeting fast training "
            "and stable performance for operational monitoring."
        ),
        url="https://dl.acm.org/doi/10.1145/3394486.3403392",
        published="2020",
        source="curated",
        relevance=0.83,
        concepts=["time series", "adversarial training", "autoencoder", "unsupervised"],
    ),
    PaperRecord(
        title="LSTM-based Encoder-Decoder for Multi-sensor Anomaly Detection",
        authors=["Pankaj Malhotra", "Anusha Ramakrishnan", "Gaurangi Anand", "Lovekesh Vig", "Puneet Agarwal", "Gautam Shroff"],
        abstract=(
            "Trains a recurrent encoder-decoder on normal sequences only and scores "
            "anomalies by reconstruction error, showing that temporal context substantially "
            "improves detection over per-observation models."
        ),
        url="https://arxiv.org/abs/1607.00148",
        published="2016",
        source="curated",
        relevance=0.86,
        concepts=["LSTM", "reconstruction error", "temporal context", "sequence model"],
    ),
    PaperRecord(
        title="A Survey of Network Anomaly Detection Techniques",
        authors=["Mohiuddin Ahmed", "Abdun Naser Mahmood", "Jiankun Hu"],
        abstract=(
            "Reviews classification, statistical, information-theoretic and clustering "
            "approaches to network anomaly detection, and catalogues the practical "
            "obstacles: class imbalance, concept drift, and the scarcity of labelled traffic."
        ),
        url="https://www.sciencedirect.com/science/article/pii/S1084804515002891",
        published="2016",
        source="curated",
        relevance=0.87,
        concepts=["survey", "class imbalance", "concept drift", "network traffic"],
    ),
    PaperRecord(
        title="Deep Anomaly Detection with Deviation Networks",
        authors=["Guansong Pang", "Chunhua Shen", "Anton van den Hengel"],
        abstract=(
            "Uses a small number of labelled anomalies to directly optimise an anomaly "
            "score via a deviation loss, rather than learning a full normality model -- "
            "an end-to-end alternative that is effective under weak supervision."
        ),
        url="https://arxiv.org/abs/1911.08623",
        published="2019",
        source="curated",
        relevance=0.8,
        concepts=["weak supervision", "deviation loss", "anomaly scoring", "deep learning"],
    ),
    PaperRecord(
        title="Efficient Algorithms for Mining Outliers from Large Data Sets",
        authors=["Sridhar Ramaswamy", "Rajeev Rastogi", "Kyuseok Shim"],
        abstract=(
            "Formalises distance-based outliers by k-nearest-neighbour distance and gives "
            "partition-based pruning algorithms that scale to large datasets. A foundational "
            "reference for distance-based anomaly scoring."
        ),
        url="https://dl.acm.org/doi/10.1145/342009.335437",
        published="2000",
        source="curated",
        relevance=0.76,
        concepts=["distance-based outliers", "kNN", "scalability", "pruning"],
    ),
    PaperRecord(
        title="A Deep Learning Approach to Network Intrusion Detection",
        authors=["Nathan Shone", "Tran Nguyen Ngoc", "Vu Dinh Phai", "Qi Shi"],
        abstract=(
            "Proposes a nonsymmetric deep autoencoder for feature learning, stacked with a "
            "random forest classifier, and evaluates on standard NIDS benchmarks -- an "
            "example of pairing learned representations with a classical ensemble."
        ),
        url="https://ieeexplore.ieee.org/document/8264962",
        published="2018",
        source="curated",
        relevance=0.82,
        concepts=["deep autoencoder", "random forest", "feature learning", "hybrid model"],
    ),
]


def keywords_for(question: str) -> list[str]:
    """The question's content words, in the order they were written.

    Sentence order is kept deliberately: it holds noun phrases together, so
    "network anomaly detection" stays a search for network anomaly detection.
    Ranking by word length instead was measured against the live API and did
    not retrieve better papers. What did matter was dropping the interrogative
    and filler words above, which had been outranking the subject.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", question.lower())
    keywords: list[str] = []
    for word in words:
        if word not in _STOPWORDS and word not in keywords:
            keywords.append(word)
    return keywords or ["anomaly", "detection"]


def build_query(question: str, terms: int = 3) -> str:
    """Turn a research question into an arXiv boolean query."""
    keywords = keywords_for(question)[:terms]
    return " AND ".join(f'all:"{w}"' for w in keywords)


def build_broad_query(question: str) -> str:
    """A looser query for when the specific one matches nothing."""
    keywords = keywords_for(question)[:4]
    return " OR ".join(f'all:"{w}"' for w in keywords)


def _score_relevance(question: str, title: str, abstract: str) -> float:
    """Cheap lexical overlap score; the Scout agent refines this."""
    words = {w for w in re.findall(r"[a-z]{4,}", question.lower()) if w not in _STOPWORDS}
    if not words:
        return 0.5
    haystack = f"{title} {abstract}".lower()
    hits = sum(1 for w in words if w in haystack)
    return round(min(0.35 + 0.65 * hits / len(words), 1.0), 3)


def search_arxiv(
    question: str, max_results: int = 12, query: str | None = None
) -> list[PaperRecord]:
    """Query the live arXiv API. Returns [] on any failure -- caller falls back.

    ``_last_failure`` records why an attempt came back empty so the run can
    say whether the live corpus was off, unreachable, or simply had nothing
    that matched. "Using the curated corpus" with no reason is indistinguishable
    from a silent outage.
    """
    global _last_failure
    _last_failure = None
    settings = get_settings()
    if not settings.enable_arxiv:
        _last_failure = "live arXiv search is disabled by configuration"
        return []

    params = {
        "search_query": query or build_query(question),
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        response = httpx.get(
            _ARXIV_ENDPOINT,
            params=params,
            timeout=settings.arxiv_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "GENESIS-Research-Lab/1.0"},
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except (httpx.HTTPError, ET.ParseError, OSError) as exc:
        logger.warning("arxiv search failed (%s); using curated corpus", exc)
        _last_failure = f"arXiv was unreachable ({type(exc).__name__})"
        return []

    papers: list[PaperRecord] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip().replace("\n", " ")
        title = re.sub(r"\s+", " ", title)
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip().replace("\n", " ")
        summary = re.sub(r"\s+", " ", summary)
        if not title:
            continue
        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
        ][:8]
        url = (entry.findtext(f"{_ATOM}id") or "").strip()
        published = (entry.findtext(f"{_ATOM}published") or "")[:10]
        papers.append(
            PaperRecord(
                title=title,
                authors=[a for a in authors if a],
                abstract=summary[:1400],
                url=url,
                published=published,
                source="arxiv",
                relevance=_score_relevance(question, title, summary),
            )
        )
    logger.info("arxiv returned %d papers", len(papers))
    return papers


def discover(
    question: str, max_results: int | None = None
) -> tuple[list[PaperRecord], str, str | None]:
    """Find literature for a question.

    Returns ``(papers, source, reason)``. ``source`` is ``"arxiv"``,
    ``"mixed"`` or ``"curated"``; ``reason`` explains a fallback, and is
    ``None`` when the live search carried the run on its own.
    """
    settings = get_settings()
    limit = max_results or settings.max_papers

    papers = search_arxiv(question, limit)
    reason = _last_failure
    if len(papers) >= 4:
        return papers[:limit], "arxiv", None

    # A three-term AND can be too narrow for a question whose subject is a
    # phrase rather than a word. Widen to OR before giving up on live results.
    if reason is None:
        broad = search_arxiv(question, limit, query=build_broad_query(question))
        reason = _last_failure
        if len(broad) >= 4:
            return broad[:limit], "arxiv", None
        if len(broad) > len(papers):
            papers = broad
    if reason is None and not papers:
        reason = "arXiv returned no matches for this question"

    curated = sorted(CURATED_CORPUS, key=lambda p: -p.relevance)
    for paper in curated:
        paper.relevance = max(
            paper.relevance, _score_relevance(question, paper.title, paper.abstract)
        )
    # Keep any live results we did get, then top up from the curated corpus.
    combined = papers + [p for p in curated if p.title not in {x.title for x in papers}]
    return combined[:limit], "curated" if not papers else "mixed", reason
