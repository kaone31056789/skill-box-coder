"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ComparisonView } from "@/components/lab/Comparison";
import { AgentRail, EventStream } from "@/components/lab/EventStream";
import { ExperimentPanel } from "@/components/lab/ExperimentPanel";
import {
  CodeViewer,
  FinalReport,
  InjectHypothesis,
  LiteraturePanel,
  WhyPanel,
} from "@/components/lab/Panels";
import { ResearchGraphView } from "@/components/lab/ResearchGraph";
import { RunVitals } from "@/components/lab/RunVitals";
import { Badge, Button, Led, Meter, Panel, SegTabs } from "@/components/ui/Instrument";
import { AnimatedNumber, ProgressRing, Pulse, useElapsed } from "@/components/ui/Motion";
import { Logo } from "@/components/ui/Logo";
import { api } from "@/lib/api";
import type { RunState } from "@/lib/types";
import { useRun } from "@/lib/useRun";

const PHASES: { key: RunState; short: string }[] = [
  { key: "RESEARCHING", short: "Literature" },
  { key: "HYPOTHESIS_GENERATION", short: "Hypotheses" },
  { key: "EXPERIMENT_DESIGN", short: "Design" },
  { key: "CODE_GENERATION", short: "Code" },
  { key: "RUNNING", short: "Execute" },
  { key: "ANALYZING", short: "Analyse" },
  { key: "DECISION", short: "Decide" },
];

const ACTIVE_STATES = new Set<RunState>([
  "RESEARCHING",
  "HYPOTHESIS_GENERATION",
  "EXPERIMENT_DESIGN",
  "CODE_GENERATION",
  "RUNNING",
  "ANALYZING",
  "DECISION",
]);

const VIEWS = [
  { key: "graph" as const, label: "Graph" },
  { key: "compare" as const, label: "Compare" },
];

export default function LabPage() {
  const params = useParams<{ runId: string }>();
  const searchParams = useSearchParams();
  const runId = params.runId;
  const reduced = useReducedMotion();

  const { run, events, graph, comparison, output, state, connected, error, refresh } =
    useRun(runId);

  const [tab, setTab] = useState<"graph" | "compare">("graph");
  // Pinning an experiment stops the side panel following the live one.
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [codeFor, setCodeFor] = useState<{ id: string; name: string } | null>(null);
  const [showWhy, setShowWhy] = useState(false);
  const [showPapers, setShowPapers] = useState(false);
  const [showInject, setShowInject] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const autostartedRef = useRef(false);
  const reportShownRef = useRef(false);

  const isActive = ACTIVE_STATES.has(state);
  const isDone = state === "COMPLETED";

  /* Autostart when arriving from the landing page. */
  useEffect(() => {
    if (autostartedRef.current) return;
    if (searchParams.get("autostart") !== "1") return;
    if (!run || run.state !== "CREATED") return;
    autostartedRef.current = true;
    void api.start(runId).then(refresh).catch(() => undefined);
  }, [run, runId, searchParams, refresh]);

  /* Surface the final report once, the moment the run completes. */
  useEffect(() => {
    if (isDone && run?.final_summary && !reportShownRef.current) {
      reportShownRef.current = true;
      setShowReport(true);
      setTab("compare");
    }
  }, [isDone, run?.final_summary]);

  const control = useCallback(
    async (action: "start" | "pause" | "resume" | "stop") => {
      setBusy(true);
      setActionError(null);
      try {
        await api[action](runId);
        await refresh();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Action failed");
      } finally {
        setBusy(false);
      }
    },
    [runId, refresh],
  );

  const liveExperiment = useMemo(() => {
    if (!run || run.experiments.length === 0) return null;
    const running = run.experiments.find((experiment) => experiment.status === "RUNNING");
    return running ?? run.experiments[run.experiments.length - 1];
  }, [run]);

  // Show the pinned experiment if one is selected, otherwise follow the live one.
  const currentExperiment = useMemo(() => {
    if (!run) return null;
    if (pinnedId) {
      const pinned = run.experiments.find((experiment) => experiment.id === pinnedId);
      if (pinned) return pinned;
    }
    return liveExperiment;
  }, [run, pinnedId, liveExperiment]);

  const currentRow = useMemo(
    () => comparison?.rows.find((row) => row.id === currentExperiment?.id) ?? null,
    [comparison, currentExperiment],
  );

  const isPinned = pinnedId !== null && currentExperiment?.id === pinnedId;

  const selectExperiment = useCallback(
    (experimentId: string) => setPinnedId((prev) => (prev === experimentId ? null : experimentId)),
    [],
  );

  const latestDecision = useMemo(
    () => (run && run.decisions.length > 0 ? run.decisions[run.decisions.length - 1] : null),
    [run],
  );

  const phaseIndex = PHASES.findIndex((phase) => phase.key === state);
  const progress = run ? run.experiments_completed / Math.max(run.max_experiments, 1) : 0;
  /* Fraction of the phase spine that should read as travelled. */
  const phaseProgress = isDone ? 1 : phaseIndex < 0 ? 0 : (phaseIndex + 0.5) / PHASES.length;
  const elapsed = useElapsed(run?.created_at, isActive);

  if (error && !run) {
    return (
      <main className="app flex h-screen items-center justify-center p-8">
        <div className="panel max-w-md p-6 text-center">
          <h1 className="display mb-2 text-[22px] text-[var(--bone)]">Cannot reach GENESIS</h1>
          <p className="mono mb-4 text-[11.5px] leading-relaxed text-[var(--bone-faint)]">{error}</p>
          <Link href="/" className="btn inline-flex">Back to start</Link>
        </div>
      </main>
    );
  }

  return (
    <main className="app flex h-screen flex-col gap-2 p-2.5">
      {/* ============================================================ header */}
      <motion.header
        className="panel relative flex shrink-0 items-center gap-5 px-4 py-2.5"
        initial={reduced ? false : { opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.2, 0.8, 0.3, 1] }}
      >
        <Link href="/" className="group flex items-center gap-2.5">
          <Logo size={24} animated={isActive} />
          <span
            className="display text-[24px] leading-none text-[var(--bone)] transition-colors group-hover:text-[var(--teal)]"
            style={{ textShadow: "0 2px 12px rgba(111,179,173,0.16)" }}
          >
            GENESIS
          </span>
          <span className="label hidden !text-[8.5px] lg:inline">Autonomous Research Lab</span>
        </Link>

        <div className="min-w-0 flex-1 border-l pl-5 hairline">
          <p className="truncate text-[12.5px] text-[var(--bone-dim)]" title={run?.question}>
            {run?.question ?? "Loading research run…"}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          {/* How far through the planned experiment budget the run is. */}
          {run && run.max_experiments > 0 && (
            <span className="hidden items-center gap-2 md:flex" title="Experiments completed">
              <ProgressRing
                value={progress}
                size={28}
                color={isDone ? "var(--sage)" : "var(--teal)"}
              >
                <span className="mono text-[9px] text-[var(--bone-dim)]">
                  {run.experiments_completed}
                </span>
              </ProgressRing>
            </span>
          )}

          {/* Wall-clock since the run was created — the console's proof of life. */}
          <span className="hidden items-baseline gap-1.5 md:flex" title="Elapsed">
            <span className="label !text-[8px]">elapsed</span>
            <span className="mono text-[11px] tabular-nums text-[var(--bone-dim)]">{elapsed}</span>
          </span>

          <div className="hidden items-center gap-2 xl:flex">
            {connected ? <Pulse color="var(--sage)" /> : <Led on tone="terracotta" pulse />}
            <span className="mono text-[10px] text-[var(--bone-faint)]">
              {connected ? "live" : "reconnecting"}
            </span>
          </div>

          <AnimatePresence initial={false}>
            {isActive && (
              <motion.span
                className="flex items-center gap-2 rounded border border-[rgba(111,179,173,0.28)] bg-[rgba(111,179,173,0.09)] px-2.5 py-1"
                initial={reduced ? false : { opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ duration: 0.22, ease: [0.2, 0.8, 0.3, 1] }}
              >
                <span className="spinner" aria-hidden />
                <span className="mono dots whitespace-nowrap text-[10px] uppercase tracking-[0.1em] text-[var(--teal)]">
                  researching
                </span>
              </motion.span>
            )}
          </AnimatePresence>

          {run && (
            <div className="hidden items-center gap-1.5 lg:flex">
              <Badge tone="iris">{run.llm_provider}</Badge>
              <Badge tone="teal">{run.sandbox_backend} sandbox</Badge>
            </div>
          )}
        </div>
      </motion.header>

      {/* ========================================================== controls */}
      <motion.div
        className="panel relative flex shrink-0 flex-wrap items-center gap-2 px-4 py-2.5"
        initial={reduced ? false : { opacity: 0, y: -6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.05, ease: [0.2, 0.8, 0.3, 1] }}
      >
        {/* Transport controls swap as the run changes state, so they animate
            in and out rather than popping the row's width around. */}
        <AnimatePresence mode="wait" initial={false}>
          {state === "CREATED" && (
            <motion.span key="start" {...swap(reduced)}>
              <Button variant="primary" onClick={() => void control("start")} disabled={busy}>
                Start Research
              </Button>
            </motion.span>
          )}
          {isActive && (
            <motion.span key="running" className="flex gap-2" {...swap(reduced)}>
              <Button onClick={() => void control("pause")} disabled={busy}>Pause</Button>
              <Button variant="danger" onClick={() => void control("stop")} disabled={busy}>Stop</Button>
            </motion.span>
          )}
          {state === "PAUSED" && (
            <motion.span key="paused" {...swap(reduced)}>
              <Button variant="primary" onClick={() => void control("resume")} disabled={busy}>
                Resume
              </Button>
            </motion.span>
          )}
          {isDone && (
            <motion.span key="done" {...swap(reduced)}>
              <Button variant="primary" onClick={() => setShowReport(true)}>View Final Report</Button>
            </motion.span>
          )}
        </AnimatePresence>

        <div className="mx-1 h-6 w-px bg-[var(--hairline)]" />

        <Button onClick={() => setShowWhy(true)} disabled={!run || run.decisions.length === 0}>
          Why?
        </Button>
        <Button
          onClick={() => currentExperiment && setCodeFor({ id: currentExperiment.id, name: currentExperiment.name })}
          disabled={!currentExperiment}
        >
          View Code
        </Button>
        <Button onClick={() => setShowPapers(true)} disabled={!run || run.papers.length === 0}>
          Literature {run && run.papers.length > 0 ? `(${run.papers.length})` : ""}
        </Button>
        <Button onClick={() => setShowInject(true)} disabled={!run || isDone}>
          Inject Hypothesis
        </Button>

        <SegTabs value={tab} options={VIEWS} onChange={setTab} className="ml-auto" label="View" />

        <AnimatePresence>
          {actionError && (
            <motion.span
              className="mono w-full text-[11px] text-[var(--terracotta)]"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
            >
              {actionError}
            </motion.span>
          )}
        </AnimatePresence>
      </motion.div>

      {/* ============================================================== body */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-2 lg:grid-cols-[260px_1fr_320px]">
        {/* ---------------------------------------------------------- left */}
        {/* Three stacked panels do not fit every viewport height, so the
            column scrolls rather than letting the last one spill out of its
            box and over the event log below. */}
        <div className="hidden min-h-0 flex-col gap-2 overflow-y-auto lg:flex">
          <Panel title="Run Status" className="shrink-0" delay={0.08}>
            <div className="space-y-4 p-3.5">
              <div>
                <div className="mb-1.5 flex items-baseline justify-between">
                  <span className="label">Phase</span>
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span
                      key={state}
                      className="mono text-[10.5px]"
                      style={{ color: isActive ? "var(--teal)" : "var(--bone-dim)" }}
                      initial={reduced ? false : { opacity: 0, y: 5 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -5 }}
                      transition={{ duration: 0.2 }}
                    >
                      {state.replace(/_/g, " ")}
                    </motion.span>
                  </AnimatePresence>
                </div>

                {/* A finished run has nothing to track: the seven lamps become
                    one line, and the panel stops competing with itself. */}
                {isDone ? (
                  <div className="flex items-center gap-2 py-0.5">
                    <Led on tone="sage" />
                    <span className="mono text-[10.5px] text-[var(--bone-dim)]">
                      All {PHASES.length} phases complete
                    </span>
                  </div>
                ) : (
                  /* Otherwise a spine behind the lamps, filled to the current
                     phase, so the list reads as a route rather than seven
                     independent checkboxes. */
                  <div className="relative">
                  <span className="phase-rail" aria-hidden>
                    <motion.span
                      className="phase-rail-fill"
                      initial={false}
                      animate={{ height: `${phaseProgress * 100}%` }}
                      transition={
                        reduced ? { duration: 0 } : { type: "spring", stiffness: 90, damping: 22 }
                      }
                    />
                  </span>
                  <ol className="relative space-y-1.5">
                    {PHASES.map((phase, index) => {
                      const done = phaseIndex > index || isDone;
                      const active = phaseIndex === index;
                      return (
                        <li key={phase.key} className="flex items-center gap-2">
                          <Led on={done || active} pulse={active} tone={active ? "teal" : "sage"} />
                          <motion.span
                            className="mono text-[10.5px]"
                            animate={{
                              color: active
                                ? "var(--teal)"
                                : done
                                  ? "var(--bone-dim)"
                                  : "var(--bone-faint)",
                              x: active ? 2 : 0,
                            }}
                            transition={{ duration: 0.3 }}
                          >
                            {phase.short}
                          </motion.span>
                          <AnimatePresence>
                            {active && (
                              <motion.span
                                className="activity-bar ml-1 flex-1"
                                initial={{ opacity: 0, scaleX: 0.3 }}
                                animate={{ opacity: 1, scaleX: 1 }}
                                exit={{ opacity: 0 }}
                                transition={{ duration: 0.3 }}
                              />
                            )}
                          </AnimatePresence>
                        </li>
                      );
                    })}
                  </ol>
                </div>
                )}
              </div>

              <div>
                <div className="mb-1.5 flex items-baseline justify-between">
                  <span className="label">Experiments</span>
                  <span className="mono text-[11px] text-[var(--bone-dim)]">
                    <AnimatedNumber
                      value={run?.experiments_completed ?? 0}
                      format={(value) => String(Math.round(value))}
                    />{" "}
                    / {run?.max_experiments ?? 0}
                  </span>
                </div>
                <Meter value={progress} tone="sage" live={isActive} />
              </div>

              <RunVitals comparison={comparison} />
            </div>
          </Panel>

          {/* Grows into spare height, but never collapses below a usable
              rail — it is the panel that shows which agent is alive. */}
          <Panel title="Agent Activity" className="min-h-[210px] flex-1 shrink-0" delay={0.16}>
            <div className="h-full overflow-y-auto">
              <AgentRail events={events} active={isActive} />
            </div>
          </Panel>
        </div>

        {/* -------------------------------------------------------- centre */}
        <Panel
          title={tab === "graph" ? "Research Graph" : "Experiment Comparison"}
          className="min-h-0"
          delay={0.1}
          right={
            tab === "graph" ? (
              <div className="flex items-center gap-2.5">
                {[
                  ["Hypothesis", "var(--amber)"],
                  ["Experiment", "var(--teal)"],
                  ["Success", "var(--sage)"],
                  ["Failed", "var(--terracotta)"],
                ].map(([label, color]) => (
                  <span key={label} className="flex items-center gap-1">
                    <span
                      className="h-1.5 w-1.5 rounded-full"
                      style={{ background: color, boxShadow: `0 0 5px ${color}` }}
                    />
                    <span className="mono text-[9px] text-[var(--bone-faint)]">{label}</span>
                  </span>
                ))}
              </div>
            ) : null
          }
          bodyClassName={tab === "compare" ? "overflow-y-auto p-3.5" : ""}
        >
          {/* The two views crossfade, so switching tabs does not read as the
              panel emptying and refilling. */}
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={tab}
              className="h-full"
              initial={reduced ? false : { opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduced ? { opacity: 0 } : { opacity: 0, y: -6 }}
              transition={{ duration: 0.2, ease: [0.2, 0.8, 0.3, 1] }}
            >
              {tab === "graph" ? (
                <ResearchGraphView graph={graph} onSelectExperiment={selectExperiment} />
              ) : (
                <ComparisonView
                  comparison={comparison}
                  selectedId={pinnedId}
                  onSelect={selectExperiment}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </Panel>

        {/* --------------------------------------------------------- right */}
        <Panel
          title={isPinned ? "Selected Experiment" : "Current Experiment"}
          className="hidden min-h-0 lg:flex"
          delay={0.14}
          right={
            currentExperiment ? (
              <span className="flex items-center gap-2">
                <AnimatePresence initial={false}>
                  {isPinned && (
                    <motion.button
                      type="button"
                      onClick={() => setPinnedId(null)}
                      className="mono text-[9.5px] uppercase tracking-[0.1em] text-[var(--teal)] hover:underline"
                      title="Resume following the live experiment"
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: 8 }}
                    >
                      follow live
                    </motion.button>
                  )}
                </AnimatePresence>
                <span className="mono text-[10px] text-[var(--bone-faint)]">
                  #{String(currentExperiment.index).padStart(3, "0")}
                </span>
              </span>
            ) : null
          }
        >
          {run && (
            <ExperimentPanel
              run={run}
              experiment={currentExperiment}
              row={currentRow}
              decision={latestDecision}
              output={currentExperiment ? output[currentExperiment.id] ?? [] : []}
            />
          )}
        </Panel>
      </div>

      {/* ======================================================== event log */}
      <Panel
        title="Live Event Stream"
        className="h-[168px] shrink-0"
        delay={0.18}
        right={
          <span className="mono text-[10px] text-[var(--bone-faint)]">
            <AnimatedNumber
              value={events.length}
              format={(value) => String(Math.round(value))}
              flash={false}
            />{" "}
            events
          </span>
        }
      >
        <EventStream events={events} />
      </Panel>

      {/* ============================================================ modals */}
      <CodeViewer
        experimentId={codeFor?.id ?? null}
        experimentName={codeFor?.name ?? ""}
        onClose={() => setCodeFor(null)}
      />
      {run && (
        <>
          <WhyPanel
            open={showWhy}
            onClose={() => setShowWhy(false)}
            decisions={run.decisions}
            hypotheses={run.hypotheses}
          />
          <LiteraturePanel
            open={showPapers}
            onClose={() => setShowPapers(false)}
            papers={run.papers}
          />
          <InjectHypothesis
            open={showInject}
            onClose={() => setShowInject(false)}
            runId={runId}
            onInjected={() => void refresh()}
          />
          <FinalReport
            open={showReport}
            onClose={() => setShowReport(false)}
            run={run}
            comparison={comparison}
          />
        </>
      )}
    </main>
  );
}

/** Shared enter/exit for the transport controls. */
function swap(reduced: boolean | null) {
  return {
    initial: reduced ? false : ({ opacity: 0, scale: 0.9 } as const),
    animate: { opacity: 1, scale: 1 },
    exit: reduced ? { opacity: 0 } : { opacity: 0, scale: 0.9 },
    transition: { duration: 0.2 },
  };
}
