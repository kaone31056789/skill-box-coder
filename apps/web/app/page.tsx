"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BlurText, SpotlightCard, useScrollReveals } from "@/components/react-bits/Motion";
import { Constellation } from "@/components/lab/Constellation";
import { Button, Led } from "@/components/ui/Instrument";
import { Wordmark } from "@/components/ui/Logo";
import { api } from "@/lib/api";
import type { SystemStatus } from "@/lib/types";

const DEFAULT_QUESTION =
  "Can we improve network anomaly detection while reducing false positives?";

const PIPELINE = [
  ["Scout", "Searches literature, extracts concepts and open research gaps"],
  ["Scientist", "Generates competing, falsifiable hypotheses"],
  ["Experimentalist", "Designs a reproducible experiment"],
  ["Engineer", "Writes executable Python — and repairs it when it fails"],
  ["Runner", "Executes in an isolated sandbox: no network, no host access"],
  ["Analyst", "Interprets the measured metrics against the hypothesis"],
  ["Principal Investigator", "Decides what to run next, and explains why"],
] as const;

/** Research depth presets. The number is the experiment budget the PI is
 *  given; the label is what that actually means for the run. */
const LEVELS = [
  { key: "rapid", label: "Rapid", count: 2, blurb: "2 experiments · fastest" },
  { key: "standard", label: "Standard", count: 3, blurb: "3 experiments · recommended" },
  { key: "thorough", label: "Thorough", count: 4, blurb: "4 experiments · deeper search" },
  { key: "exhaustive", label: "Exhaustive", count: 5, blurb: "5 experiments · widest search" },
] as const;

const PROOF = [
  ["0.364 → 0.984", "F1, baseline to best"],
  ["4.27% → 0.24%", "False-positive rate"],
  ["100%", "Metrics from executed code"],
] as const;

export default function Landing() {
  const router = useRouter();
  const revealRef = useScrollReveals();
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [experiments, setExperiments] = useState(3);
  const [busy, setBusy] = useState<"start" | "demo" | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .systemStatus()
      .then(setStatus)
      .catch((err: Error) => setError(err.message));
  }, []);

  async function launch(demo: boolean) {
    setBusy(demo ? "demo" : "start");
    setError(null);
    try {
      const { id } = await api.createRun({
        question: demo ? DEFAULT_QUESTION : question.trim(),
        max_experiments: demo ? 3 : experiments,
        demo_mode: demo,
      });
      router.push(`/lab/${id}?autostart=1`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the research run");
      setBusy(null);
    }
  }

  return (
    <main className="landing">
      <div className="landing-container" ref={revealRef}>
        <header className="landing-header">
          <Wordmark size={28} subtitle="Autonomous Research Laboratory" />
          <nav aria-label="Main navigation" className="landing-nav">
            <a href="#workflow">How it works</a>
            <a href="#research" className="nav-cta">New research <span aria-hidden>&#8599;</span></a>
          </nav>
        </header>

        <section id="research" className="research-card" aria-labelledby="research-heading">
          <div className="research-heading">
            <div><span className="eyebrow">Your workspace</span><h2 id="research-heading"><BlurText text="Start a new research run" /></h2><p>Define a question. Set the depth. Let the lab take it from here.</p></div>
            <span className="research-tag shiny-text">Computational research</span>
          </div>
          <label className="field-label" htmlFor="question">Research question <span>Be specific and testable</span></label>
          <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} spellCheck={false} className="question-input" placeholder="e.g. Do ensembles outperform single models under label noise?" />
          <div className="field-label depth-label" id="depth-label">Research depth <span>Choose your experiment budget</span></div>
          <div className="depth-options" role="group" aria-labelledby="depth-label">
            {LEVELS.map((level) => {
              const selected = experiments === level.count;
              return <button key={level.key} type="button" onClick={() => setExperiments(level.count)} aria-pressed={selected} className="depth-option">
                <span className="depth-title">{level.label}<span className="selection-dot" aria-hidden>{selected ? "\u2713" : ""}</span></span>
                <span className="depth-description">{level.count} experiments</span>
                <span className="depth-hint">{level.key === "standard" ? "Recommended" : level.key === "rapid" ? "A quick first exploration" : level.key === "thorough" ? "More room to investigate" : "The most comprehensive"}</span>
              </button>;
            })}
          </div>
          <div className="research-actions">
            <p><span className="trust-mark" aria-hidden>&#9671;</span> Real code. Isolated sandbox. Measured results.</p>
            <div className="action-buttons">
              <Button onClick={() => void launch(true)} disabled={busy !== null} loading={busy === "demo"}>{busy === "demo" ? "Loading..." : "Try a demo"}</Button>
              <Button variant="primary" onClick={() => void launch(false)} disabled={busy !== null || question.trim().length < 8} loading={busy === "start"}>{busy === "start" ? "Initialising..." : "Begin research"}<span aria-hidden>&#8599;</span></Button>
            </div>
          </div>
          <p className="run-note">Research runs take a few minutes. The demo uses deterministic reasoning and finishes in seconds; both execute real experiments.</p>
          {error && <p role="alert" className="research-error">{error}</p>}
        </section>

        <section className="landing-hero">
          <div className="hero-copy">
            <span className="eyebrow"><span className="eyebrow-line" /> From curiosity to evidence</span>
            <h1 className="display"><BlurText text="Great research starts" /><br /><BlurText text="with a better" /> <em className="gradient-text">question.</em></h1>
            <p>An autonomous lab for your next discovery. Explore the literature, test competing hypotheses, and turn real experiments into measurable results.</p>
            <div className="hero-features"><span>01 / Ask</span><span>02 / Experiment</span><span>03 / Discover</span></div>
          </div>
          <SpotlightCard className="hero-visual">
            <div className="visual-caption"><span className="label">The discovery engine</span><span className="mono">GENESIS / 01</span></div>
            <Constellation />
            <div className="visual-footer"><Led on tone="teal" /><span>Seven specialised agents. One research loop.</span></div>
          </SpotlightCard>
        </section>

        <section className="evidence-section" aria-label="Demo benchmark results">
          <div className="evidence-intro"><span className="eyebrow">Evidence, not estimates</span><p>Network anomaly detection<br /><span>Results from the demo benchmark</span></p></div>
          {PROOF.map(([value, label]) => <div className="evidence-stat" data-reveal key={label}><div className="mono">{value}</div><p>{label}</p></div>)}
        </section>

        <section id="workflow" className="workflow-section">
          <div className="workflow-heading"><div><span className="eyebrow">Built to follow the evidence</span><h2 className="display"><BlurText text="A complete research team." /><br /><BlurText text="One continuous loop." /></h2></div><p>Each agent has a defined role. Every finding informs what happens next, from the first paper to the final result.</p></div>
          <ol className="workflow-grid">{PIPELINE.map(([name, description], index) => <li key={name} data-reveal><SpotlightCard><span className="workflow-number mono">{String(index + 1).padStart(2, "0")}</span><h3>{name}</h3><p>{description}</p></SpotlightCard></li>)}</ol>
        </section>
        <footer className="landing-footer"><span>GENESIS <span className="footer-separator">/</span> Autonomous Research Laboratory</span><div className="footer-status"><Led on={!!status} tone={status ? "sage" : "amber"} /><span>{status ? `${status.llm_provider} reasoning \u00b7 ${status.sandbox_backend} sandbox` : "Connecting to laboratory"}</span></div></footer>
      </div>
    </main>
  );
}
