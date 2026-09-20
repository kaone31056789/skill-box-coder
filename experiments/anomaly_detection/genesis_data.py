"""Deterministic synthetic network-flow dataset for GENESIS experiments.

This module is TRUSTED code, copied into the sandbox alongside the untrusted
AI-generated experiment. It ships the dataset with the experiment so the
sandbox never needs network access.

Design intent
-------------
The dataset is built so that different modelling approaches genuinely differ
in performance -- nothing about the outcome is staged:

* ``exfiltration`` anomalies are separable from per-flow features alone
  (very long duration, very large dst_bytes), so a naive baseline gets
  meaningful-but-limited recall.
* ``port_scan`` anomalies are deliberately NOT separable per-flow: each
  individual scan flow looks like an ordinary short DNS/probe request. They
  only become visible in a time window, via the number of distinct
  destination ports a source touches.
* ``ddos_burst`` anomalies are weakly separable per-flow (small packets) but
  strongly separable with windowed packet-rate features.

So a model given ``feature_set="temporal"`` should genuinely outperform one
given ``feature_set="base"``. That gap is discovered by execution, not
hard-coded.
"""
from __future__ import annotations

import numpy as np

__all__ = [
    "BASE_FEATURES",
    "TEMPORAL_FEATURES",
    "generate_flows",
    "load_dataset",
    "describe",
]

# Per-flow features available without any temporal context.
BASE_FEATURES: list[str] = [
    "duration",
    "src_bytes",
    "dst_bytes",
    "packets",
    "pkt_size_mean",
    "dst_port",
    "protocol",
    "tcp_flags",
]

# Windowed / statistical features derived from flow history.
TEMPORAL_FEATURES: list[str] = [
    "unique_dst_ports_60s",
    "flows_from_src_60s",
    "pkt_rate",
    "bytes_ratio",
    "iat_mean_60s",
    "src_entropy_60s",
]

_WINDOW_SECONDS = 60.0

# Label encoding: 0 = normal, 1 = anomaly.
_ATTACK_KINDS = ("port_scan", "ddos_burst", "exfiltration")
_BENIGN_CONFUSERS = ("benign_monitor", "benign_backup", "flash_crowd")


def _lognormal(rng: np.random.Generator, mean: float, sigma: float, n: int) -> np.ndarray:
    return rng.lognormal(mean=mean, sigma=sigma, size=n)


def generate_flows(
    n_normal: int = 5200,
    seed: int = 42,
    contamination: float = 0.085,
) -> dict[str, np.ndarray]:
    """Generate a deterministic set of raw network flows.

    Returns a dict of column-name -> array, including ``timestamp``, ``src_id``,
    ``label`` and ``attack_kind``.
    """
    rng = np.random.default_rng(seed)

    n_attack = int(round(n_normal * contamination / (1.0 - contamination)))
    # Split attacks across the three families.
    n_scan = int(round(n_attack * 0.45))
    n_ddos = int(round(n_attack * 0.35))
    n_exfil = max(n_attack - n_scan - n_ddos, 1)

    cols: dict[str, list[np.ndarray]] = {
        k: []
        for k in (
            "timestamp",
            "src_id",
            "duration",
            "src_bytes",
            "dst_bytes",
            "packets",
            "dst_port",
            "protocol",
            "tcp_flags",
            "label",
            "attack_kind",
        )
    }

    def _push(**kwargs: np.ndarray) -> None:
        for key, value in kwargs.items():
            cols[key].append(value)

    horizon = 3600.0  # one hour of traffic

    # ------------------------------------------------------------------
    # Normal traffic: three service profiles (web, dns, db)
    # ------------------------------------------------------------------
    profile_share = (0.55, 0.30, 0.15)
    n_web = int(n_normal * profile_share[0])
    n_dns = int(n_normal * profile_share[1])
    n_db = n_normal - n_web - n_dns

    # -- web (HTTPS): moderate duration, asymmetric bytes
    _push(
        timestamp=rng.uniform(0, horizon, n_web),
        src_id=rng.integers(0, 240, n_web),
        duration=_lognormal(rng, 0.5, 0.8, n_web),
        src_bytes=_lognormal(rng, 6.2, 0.9, n_web),
        dst_bytes=_lognormal(rng, 8.6, 1.0, n_web),
        packets=rng.integers(8, 90, n_web).astype(float),
        dst_port=np.full(n_web, 443.0),
        protocol=np.full(n_web, 6.0),  # TCP
        tcp_flags=rng.choice([24.0, 25.0, 26.0], size=n_web, p=[0.7, 0.2, 0.1]),
        label=np.zeros(n_web),
        attack_kind=np.full(n_web, "none", dtype=object),
    )

    # -- dns: very short, tiny payloads. NOTE: port-scan flows deliberately
    #    overlap with this profile in per-flow feature space.
    _push(
        timestamp=rng.uniform(0, horizon, n_dns),
        src_id=rng.integers(0, 240, n_dns),
        duration=_lognormal(rng, -2.4, 0.55, n_dns),
        src_bytes=_lognormal(rng, 4.0, 0.45, n_dns),
        dst_bytes=_lognormal(rng, 4.6, 0.55, n_dns),
        packets=rng.integers(2, 7, n_dns).astype(float),
        dst_port=np.full(n_dns, 53.0),
        protocol=np.full(n_dns, 17.0),  # UDP
        tcp_flags=np.zeros(n_dns),
        label=np.zeros(n_dns),
        attack_kind=np.full(n_dns, "none", dtype=object),
    )

    # -- db: long-lived, chatty
    _push(
        timestamp=rng.uniform(0, horizon, n_db),
        src_id=rng.integers(0, 60, n_db),
        duration=_lognormal(rng, 2.3, 0.7, n_db),
        src_bytes=_lognormal(rng, 7.4, 0.8, n_db),
        dst_bytes=_lognormal(rng, 9.1, 0.9, n_db),
        packets=rng.integers(40, 400, n_db).astype(float),
        dst_port=np.full(n_db, 5432.0),
        protocol=np.full(n_db, 6.0),
        tcp_flags=rng.choice([24.0, 16.0], size=n_db, p=[0.8, 0.2]),
        label=np.zeros(n_db),
        attack_kind=np.full(n_db, "none", dtype=object),
    )

    # ------------------------------------------------------------------
    # Benign confusers. These are LABELLED NORMAL but deliberately mimic an
    # attack family in per-flow feature space. They are the reason a per-flow
    # model produces false positives, and each one is separable only via a
    # windowed feature -- which is what makes the temporal feature set win.
    # ------------------------------------------------------------------
    n_monitor = int(n_normal * 0.045)
    n_backup = int(n_normal * 0.02)
    n_flash = int(n_normal * 0.05)

    # -- benign_monitor: health checks. Looks exactly like a port scan per-flow
    #    (SYN, tiny, short) but touches a small FIXED set of service ports at a
    #    regular cadence -> low unique_dst_ports_60s, regular iat.
    monitor_ports = np.array([80.0, 443.0, 22.0, 53.0, 5432.0, 6379.0, 9090.0, 3000.0])
    monitor_src = rng.integers(500, 508, n_monitor)
    _push(
        timestamp=np.sort(rng.uniform(0, horizon, n_monitor)),
        src_id=monitor_src,
        duration=_lognormal(rng, -2.3, 0.6, n_monitor),
        src_bytes=_lognormal(rng, 4.1, 0.5, n_monitor),
        dst_bytes=_lognormal(rng, 4.4, 0.6, n_monitor),
        packets=rng.integers(2, 7, n_monitor).astype(float),
        dst_port=rng.choice(monitor_ports, size=n_monitor),
        protocol=np.full(n_monitor, 6.0),
        tcp_flags=rng.choice([2.0, 0.0], size=n_monitor, p=[0.85, 0.15]),
        label=np.zeros(n_monitor),
        attack_kind=np.full(n_monitor, "benign_monitor", dtype=object),
    )

    # -- benign_backup: nightly transfers. Looks like exfiltration per-flow
    #    (long, huge outbound) but recurs from a handful of known hosts, so
    #    flows_from_src_60s is high where real exfiltration is a one-off.
    backup_src = rng.integers(400, 403, n_backup)
    backup_anchor = rng.uniform(0, horizon - 200.0, 3)
    _push(
        timestamp=backup_anchor[backup_src - 400] + rng.uniform(0, 150.0, n_backup),
        src_id=backup_src,
        duration=_lognormal(rng, 4.4, 0.55, n_backup),
        src_bytes=_lognormal(rng, 12.3, 0.65, n_backup),
        dst_bytes=_lognormal(rng, 5.0, 0.7, n_backup),
        packets=rng.integers(500, 3800, n_backup).astype(float),
        dst_port=rng.choice([22.0, 443.0], size=n_backup, p=[0.7, 0.3]),
        protocol=np.full(n_backup, 6.0),
        tcp_flags=rng.choice([24.0, 16.0], size=n_backup, p=[0.6, 0.4]),
        label=np.zeros(n_backup),
        attack_kind=np.full(n_backup, "benign_backup", dtype=object),
    )

    # -- flash_crowd: a legitimate traffic spike. Per-flow identical to a DDoS
    #    burst, but originates from MANY distinct sources -> high
    #    src_entropy_60s, where a DDoS burst collapses entropy.
    flash_anchor = rng.uniform(0, horizon - 90.0, 2)
    flash_which = rng.integers(0, 2, n_flash)
    _push(
        timestamp=flash_anchor[flash_which] + rng.uniform(0, 35.0, n_flash),
        src_id=rng.integers(1000, 1000 + max(n_flash // 2, 50), n_flash),
        duration=_lognormal(rng, -2.9, 0.45, n_flash),
        src_bytes=_lognormal(rng, 3.7, 0.45, n_flash),
        dst_bytes=_lognormal(rng, 3.1, 0.55, n_flash),
        packets=rng.integers(3, 15, n_flash).astype(float),
        dst_port=rng.choice([80.0, 443.0], size=n_flash, p=[0.6, 0.4]),
        protocol=np.full(n_flash, 6.0),
        tcp_flags=rng.choice([2.0, 24.0], size=n_flash, p=[0.8, 0.2]),
        label=np.zeros(n_flash),
        attack_kind=np.full(n_flash, "flash_crowd", dtype=object),
    )

    # ------------------------------------------------------------------
    # Attack 1: port scan -- per-flow this mimics benign short probes.
    # Detectable only via distinct-destination-port count per source/window.
    # ------------------------------------------------------------------
    n_scanners = max(n_scan // 40, 2)
    scan_src = rng.integers(900, 900 + n_scanners, n_scan)
    # Each scanner works a tight time burst, hitting many distinct ports.
    burst_start = rng.uniform(0, horizon - 120.0, n_scanners)
    scan_ts = burst_start[scan_src - 900] + rng.uniform(0, 45.0, n_scan)
    _push(
        timestamp=scan_ts,
        src_id=scan_src,
        duration=_lognormal(rng, -2.3, 0.6, n_scan),
        src_bytes=_lognormal(rng, 4.1, 0.5, n_scan),
        dst_bytes=_lognormal(rng, 4.4, 0.6, n_scan),
        packets=rng.integers(2, 7, n_scan).astype(float),
        dst_port=rng.integers(1, 65535, n_scan).astype(float),
        protocol=np.full(n_scan, 6.0),
        tcp_flags=rng.choice([2.0, 0.0], size=n_scan, p=[0.85, 0.15]),
        label=np.ones(n_scan),
        attack_kind=np.full(n_scan, "port_scan", dtype=object),
    )

    # ------------------------------------------------------------------
    # Attack 2: DDoS burst -- many tiny flows from few sources, very fast.
    # Weakly visible per-flow, strongly visible via packet rate + flow count.
    # ------------------------------------------------------------------
    n_ddos_src = max(n_ddos // 60, 2)
    ddos_src = rng.integers(700, 700 + n_ddos_src, n_ddos)
    ddos_burst_start = rng.uniform(0, horizon - 90.0, n_ddos_src)
    ddos_ts = ddos_burst_start[ddos_src - 700] + rng.uniform(0, 30.0, n_ddos)
    ddos_duration = _lognormal(rng, -3.0, 0.4, n_ddos)
    _push(
        timestamp=ddos_ts,
        src_id=ddos_src,
        duration=ddos_duration,
        src_bytes=_lognormal(rng, 3.6, 0.4, n_ddos),
        dst_bytes=_lognormal(rng, 2.9, 0.5, n_ddos),
        packets=rng.integers(3, 14, n_ddos).astype(float),
        dst_port=np.full(n_ddos, 80.0),
        protocol=np.full(n_ddos, 6.0),
        tcp_flags=np.full(n_ddos, 2.0),
        label=np.ones(n_ddos),
        attack_kind=np.full(n_ddos, "ddos_burst", dtype=object),
    )

    # ------------------------------------------------------------------
    # Attack 3: exfiltration -- long, huge outbound transfer.
    # Clearly separable from per-flow features alone.
    # ------------------------------------------------------------------
    _push(
        timestamp=rng.uniform(0, horizon, n_exfil),
        src_id=rng.integers(0, 60, n_exfil),
        duration=_lognormal(rng, 4.6, 0.5, n_exfil),
        src_bytes=_lognormal(rng, 12.6, 0.6, n_exfil),
        dst_bytes=_lognormal(rng, 5.2, 0.7, n_exfil),
        packets=rng.integers(600, 4000, n_exfil).astype(float),
        dst_port=rng.choice([443.0, 22.0, 8080.0], size=n_exfil),
        protocol=np.full(n_exfil, 6.0),
        tcp_flags=rng.choice([24.0, 16.0], size=n_exfil, p=[0.6, 0.4]),
        label=np.ones(n_exfil),
        attack_kind=np.full(n_exfil, "exfiltration", dtype=object),
    )

    data = {k: np.concatenate(v) for k, v in cols.items()}

    # Sort chronologically -- required for the windowed features to mean anything.
    order = np.argsort(data["timestamp"], kind="stable")
    data = {k: v[order] for k, v in data.items()}

    # Measurement jitter. Real collectors are noisy, and without this a
    # supervised model memorises the exact generative signature and scores a
    # meaningless F1 = 1.0.
    for column, scale in (
        ("duration", 0.10),
        ("src_bytes", 0.12),
        ("dst_bytes", 0.12),
        ("packets", 0.08),
    ):
        noise = rng.normal(1.0, scale, size=len(data[column]))
        data[column] = np.maximum(data[column] * np.abs(noise), 1e-4)

    data["pkt_size_mean"] = (data["src_bytes"] + data["dst_bytes"]) / np.maximum(
        data["packets"], 1.0
    )
    return data


def _temporal_features(data: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Compute windowed features over a chronologically sorted flow table.

    Uses a two-pointer sweep over the sorted timestamps: O(n * window_occupancy)
    rather than O(n^2).
    """
    ts = data["timestamp"]
    src = data["src_id"]
    port = data["dst_port"]
    packets = data["packets"]
    duration = data["duration"]
    src_bytes = data["src_bytes"]
    dst_bytes = data["dst_bytes"]

    n = len(ts)
    unique_ports = np.zeros(n)
    flows_from_src = np.zeros(n)
    iat_mean = np.zeros(n)
    src_entropy = np.zeros(n)

    left = 0
    for i in range(n):
        while ts[i] - ts[left] > _WINDOW_SECONDS:
            left += 1
        window_src = src[left : i + 1]
        same_src = window_src == src[i]

        unique_ports[i] = len(np.unique(port[left : i + 1][same_src]))
        flows_from_src[i] = int(same_src.sum())

        src_ts = ts[left : i + 1][same_src]
        iat_mean[i] = float(np.mean(np.diff(src_ts))) if src_ts.size > 1 else _WINDOW_SECONDS

        # Shannon entropy of the source distribution in the window: a burst
        # dominated by one source collapses entropy.
        _, counts = np.unique(window_src, return_counts=True)
        probabilities = counts / counts.sum()
        src_entropy[i] = float(-(probabilities * np.log2(probabilities)).sum())

    return {
        "unique_dst_ports_60s": unique_ports,
        "flows_from_src_60s": flows_from_src,
        "pkt_rate": packets / np.maximum(duration, 1e-3),
        "bytes_ratio": src_bytes / np.maximum(dst_bytes, 1.0),
        "iat_mean_60s": iat_mean,
        "src_entropy_60s": src_entropy,
    }


def load_dataset(
    feature_set: str = "base",
    seed: int = 42,
    test_size: float = 0.3,
    n_normal: int = 5200,
    contamination: float = 0.085,
):
    """Load the anomaly-detection dataset.

    Parameters
    ----------
    feature_set:
        ``"base"``     -> per-flow features only (see ``BASE_FEATURES``).
        ``"temporal"`` -> base + windowed features (see ``TEMPORAL_FEATURES``).
    seed:
        Controls both data generation and the train/test split.
    test_size:
        Fraction held out for evaluation.

    Returns
    -------
    ``(X_train, X_test, y_train, y_test, feature_names)`` where ``X`` arrays are
    float64 ``ndarray`` and ``y`` arrays are int (0 = normal, 1 = anomaly).

    The split is chronological (train = earlier flows, test = later flows),
    which is the honest evaluation protocol for temporal traffic data.
    """
    data = generate_flows(n_normal=n_normal, seed=seed, contamination=contamination)

    names = list(BASE_FEATURES)
    columns = [data[name] for name in BASE_FEATURES]

    if feature_set == "temporal":
        temporal = _temporal_features(data)
        for name in TEMPORAL_FEATURES:
            names.append(name)
            columns.append(temporal[name])
    elif feature_set != "base":
        raise ValueError(f"unknown feature_set {feature_set!r}; use 'base' or 'temporal'")

    X = np.column_stack(columns).astype(np.float64)
    y = data["label"].astype(int)

    # Chronological split: the table is already time-sorted.
    split_at = int(len(y) * (1.0 - test_size))
    X_train, X_test = X[:split_at], X[split_at:]
    y_train, y_test = y[:split_at], y[split_at:]
    return X_train, X_test, y_train, y_test, names


def describe(seed: int = 42) -> dict[str, object]:
    """Summary of the generated dataset, used by the Experimentalist agent."""
    data = generate_flows(seed=seed)
    labels = data["label"].astype(int)
    kinds = data["attack_kind"]
    breakdown = {k: int((kinds == k).sum()) for k in _ATTACK_KINDS}
    confusers = {k: int((kinds == k).sum()) for k in _BENIGN_CONFUSERS}
    return {
        "n_samples": int(len(labels)),
        "n_anomalies": int(labels.sum()),
        "anomaly_rate": round(float(labels.mean()), 4),
        "attack_breakdown": breakdown,
        "benign_confusers": confusers,
        "base_features": BASE_FEATURES,
        "temporal_features": TEMPORAL_FEATURES,
        "split": "chronological, 70/30",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(describe(), indent=2))
