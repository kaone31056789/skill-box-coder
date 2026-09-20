"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Empty, Led } from "@/components/ui/Instrument";
import { AnimatedNumber } from "@/components/ui/Motion";
import type { AgentEvent, AgentName, EventStatus } from "@/lib/types";

const AGENT_TONE: Record<AgentName, string> = {
  SCOUT: "var(--iris)",
  SCIENTIST: "var(--amber)",
  EXPERIMENTALIST: "var(--teal)",
  ENGINEER: "var(--bone-dim)",
  RUNNER: "var(--teal)",
  ANALYST: "var(--sage)",
  PI: "var(--iris)",
  SYSTEM: "var(--bone-faint)",
};

const STATUS_MARK: Record<EventStatus, string> = {
  info: "·",
  success: "✓",
  warning: "↻",
  error: "✗",
};

const STATUS_TONE: Record<EventStatus, string> = {
  info: "var(--bone-faint)",
  success: "var(--sage)",
  warning: "var(--amber)",
  error: "var(--terracotta)",
};

function clockOf(timestamp: string | null): string {
  if (!timestamp) return "--:--:--";
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime())
    ? "--:--:--"
    : date.toLocaleTimeString("en-GB", { hour12: false });
}

export function EventStream({ events }: { events: AgentEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  /* Follow the tail, but stop fighting the user if they scroll up to read —
     and tell them how much they missed while they were up there. */
  const [pinned, setPinned] = useState(true);
  /* While pinned, everything is by definition seen; the baseline freezes the
     moment the reader scrolls up, and the gap becomes the unseen count. */
  const [seen, setSeen] = useState(events.length);
  if (pinned && seen !== events.length) setSeen(events.length);
  const unseen = Math.max(0, events.length - seen);

  useEffect(() => {
    const element = scrollRef.current;
    if (element && pinned) element.scrollTop = element.scrollHeight;
  }, [events, pinned]);

  function onScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    setPinned(distance < 48);
  }

  function jumpToTail() {
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior: reduced ? "auto" : "smooth" });
    setPinned(true);
  }

  if (events.length === 0) {
    return <Empty>Agent activity will stream here in real time.</Empty>;
  }

  return (
    <div className="relative h-full">
      <div ref={scrollRef} onScroll={onScroll} className="h-full overflow-y-auto px-3 py-2">
        <ul className="space-y-px">
          {events.map((event, index) => {
            const tone = AGENT_TONE[event.agent] ?? "var(--bone-dim)";
            return (
              <motion.li
                key={`${event.seq}-${index}`}
                className="event-row grid grid-cols-[62px_104px_14px_1fr] items-baseline gap-2 rounded px-2 py-[3px]"
                style={{ ["--agent-tone" as string]: tone }}
                initial={reduced ? false : { opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.26, ease: [0.2, 0.8, 0.3, 1] }}
              >
                <time className="mono text-[10px] text-[var(--bone-faint)]">
                  {clockOf(event.timestamp)}
                </time>
                <span
                  className="mono text-[10px] font-medium uppercase tracking-[0.1em]"
                  style={{ color: tone }}
                >
                  {event.agent}
                </span>
                <span
                  className="mono text-[10px]"
                  style={{ color: STATUS_TONE[event.status] }}
                  aria-label={event.status}
                >
                  {STATUS_MARK[event.status] ?? "·"}
                </span>
                <span className="text-[12px] leading-snug text-[var(--bone-dim)]">
                  {event.message}
                </span>
              </motion.li>
            );
          })}
        </ul>
      </div>

      <AnimatePresence>
        {!pinned && unseen > 0 && (
          <motion.button
            type="button"
            className="tail-pill"
            onClick={jumpToTail}
            initial={{ opacity: 0, y: 10, x: "-50%" }}
            animate={{ opacity: 1, y: 0, x: "-50%" }}
            exit={{ opacity: 0, y: 10, x: "-50%" }}
            transition={{ type: "spring", stiffness: 380, damping: 28 }}
          >
            <span aria-hidden>↓</span>
            {unseen} new {unseen === 1 ? "event" : "events"}
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Seconds since the last event — proves the run is alive during long calls. */
function useSecondsSince(timestamp: string | null | undefined, running: boolean): number {
  /* The clock is the only state; the elapsed figure is derived from it, so
     stopping simply means no longer ticking. */
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running || !timestamp) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [timestamp, running]);

  if (!running || !timestamp) return 0;
  const started = new Date(timestamp).getTime();
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Math.round((now - started) / 1000));
}

/** Per-agent status rail: which agent is live right now, and who has run. */
export function AgentRail({ events, active }: { events: AgentEvent[]; active: boolean }) {
  const reduced = useReducedMotion();
  const agents: AgentName[] = [
    "SCOUT",
    "SCIENTIST",
    "EXPERIMENTALIST",
    "ENGINEER",
    "RUNNER",
    "ANALYST",
    "PI",
  ];
  const latest = events.length > 0 ? events[events.length - 1] : null;
  const waiting = useSecondsSince(latest?.timestamp, active);

  /* One pass for both "has this agent run" and "how much of the run was it" —
     the share bar is what makes a stalled agent visible at a glance. */
  const { counts, busiest, lastAction } = useMemo(() => {
    const tally = new Map<AgentName, number>();
    const action = new Map<AgentName, string>();
    for (const event of events) {
      tally.set(event.agent, (tally.get(event.agent) ?? 0) + 1);
      action.set(event.agent, event.action);
    }
    return {
      counts: tally,
      busiest: Math.max(1, ...agents.map((agent) => tally.get(agent) ?? 0)),
      lastAction: action,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  return (
    <>
      <AnimatePresence initial={false}>
        {active && (
          <motion.div
            className="overflow-hidden border-b hairline"
            initial={reduced ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.2, 0.8, 0.3, 1] }}
          >
            <div className="px-3 py-2.5">
              <div className="mb-1.5 flex items-baseline justify-between">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span
                    key={latest?.agent ?? "GENESIS"}
                    className="label !text-[var(--teal)]"
                    initial={reduced ? false : { opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -5 }}
                    transition={{ duration: 0.18 }}
                  >
                    {latest ? latest.agent : "GENESIS"} working
                  </motion.span>
                </AnimatePresence>
                <span className="mono text-[10px] text-[var(--bone-faint)]">{waiting}s</span>
              </div>
              <div className="activity-bar" />
              <AnimatePresence>
                {waiting > 45 && (
                  <motion.p
                    className="mono mt-1.5 text-[9.5px] leading-snug text-[var(--bone-faint)]"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                  >
                    Long model call — reasoning steps can take up to a minute.
                  </motion.p>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <ul className="space-y-1 p-3">
        {agents.map((agent) => {
          const isCurrent = active && latest?.agent === agent;
          const count = counts.get(agent) ?? 0;
          const hasRun = count > 0;
          return (
            <li
              key={agent}
              className={`relative flex items-center gap-2.5 overflow-hidden rounded px-2 py-1.5 ${
                isCurrent ? "active-row" : ""
              }`}
              style={isCurrent ? { boxShadow: "inset 0 0 0 1px rgba(111,179,173,0.22)" } : undefined}
            >
              {/* Share of the run's traffic, as a quiet backing bar. */}
              <motion.span
                className="pointer-events-none absolute inset-y-0 left-0 rounded"
                style={{ background: `${AGENT_TONE[agent]}12` }}
                initial={false}
                animate={{ width: `${(count / busiest) * 100}%` }}
                transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 110, damping: 24 }}
                aria-hidden
              />
              {isCurrent ? (
                <span className="spinner relative" aria-label="working" />
              ) : (
                <Led on={hasRun} tone={hasRun ? "sage" : "bone"} />
              )}
              <span
                className="mono relative w-[100px] shrink-0 text-[10px] uppercase tracking-[0.1em]"
                style={{
                  color: isCurrent
                    ? "var(--teal)"
                    : hasRun
                      ? "var(--bone-dim)"
                      : "var(--bone-faint)",
                }}
              >
                {agent}
              </span>
              {isCurrent ? (
                <span className="dots mono relative text-[10.5px] text-[var(--teal)]">working</span>
              ) : (
                <span className="relative truncate text-[10.5px] text-[var(--bone-faint)]">
                  {lastAction.get(agent)?.replace(/_/g, " ") ?? "idle"}
                </span>
              )}
              {count > 0 && (
                <AnimatedNumber
                  value={count}
                  format={(value) => String(Math.round(value))}
                  className="mono relative ml-auto shrink-0 text-[9.5px] text-[var(--bone-faint)]"
                />
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}
