"use client";

/**
 * Experiment source viewer.
 *
 * This is the window onto what the ENGINEER agent actually wrote and what the
 * sandbox actually printed, so it is built to be *read*: highlighted source, a
 * line gutter you can anchor on, a find bar, and a scroll rail that shows how
 * much of a long file is left. Lines stream in on open, which makes switching
 * tabs feel like the pane is loading rather than blinking.
 */
import { AnimatePresence, motion, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";

import { Badge, Button, Modal, SegTabs } from "@/components/ui/Instrument";
import { api } from "@/lib/api";
import { TOKEN_COLOR, highlightLines, type Language } from "@/lib/highlight";
import type { ExperimentResults } from "@/lib/types";

type Tab = "code" | "stdout" | "stderr";

const TABS = [
  { key: "code" as const, label: "code" },
  { key: "stdout" as const, label: "stdout" },
  { key: "stderr" as const, label: "stderr" },
];

/** Beyond this many rows the entrance stagger is dropped — a 400-line log
 *  should not take four seconds to become readable. */
const STAGGER_LIMIT = 90;

function filenameFor(name: string): string {
  const slug = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  return `${slug || "experiment"}.py`;
}

/** Copy button that confirms in place rather than via a toast. */
function CopyButton({ text, disabled }: { text: string; disabled?: boolean }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(timer);
  }, [copied]);

  return (
    <Button
      disabled={disabled}
      title="Copy to clipboard"
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => setCopied(true))
          .catch(() => undefined);
      }}
    >
      <span className="relative inline-flex min-w-[52px] justify-center">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={copied ? "copied" : "copy"}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.16 }}
            style={copied ? { color: "var(--sage)" } : undefined}
          >
            {copied ? "copied ✓" : "copy"}
          </motion.span>
        </AnimatePresence>
      </span>
    </Button>
  );
}

/** One highlighted source row, with its gutter number. */
function CodeLine({
  number,
  tokens,
  wrap,
  dimmed,
  matched,
  animate,
  delay,
}: {
  number: number;
  tokens: { kind: keyof typeof TOKEN_COLOR; value: string }[];
  wrap: boolean;
  dimmed: boolean;
  matched: boolean;
  animate: boolean;
  delay: number;
}) {
  const content = (
    <>
      <span className="code-gutter" aria-hidden>
        {number}
      </span>
      <code className={wrap ? "code-text code-wrap" : "code-text"}>
        {tokens.length === 0 ? (
          " "
        ) : (
          tokens.map((token, index) => (
            <span key={index} style={{ color: TOKEN_COLOR[token.kind] }}>
              {token.value}
            </span>
          ))
        )}
      </code>
    </>
  );

  if (!animate) {
    return (
      <div className="code-line" data-dimmed={dimmed} data-matched={matched}>
        {content}
      </div>
    );
  }

  return (
    <motion.div
      className="code-line"
      data-dimmed={dimmed}
      data-matched={matched}
      initial={{ opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.22, delay, ease: "easeOut" }}
    >
      {content}
    </motion.div>
  );
}

export function CodeViewer({
  experimentId,
  experimentName,
  onClose,
}: {
  experimentId: string | null;
  experimentName: string;
  onClose: () => void;
}) {
  const [code, setCode] = useState<string>("");
  const [results, setResults] = useState<ExperimentResults | null>(null);
  const [tab, setTab] = useState<Tab>("code");
  const [loading, setLoading] = useState(false);
  const [wrap, setWrap] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);

  const reduced = useReducedMotion();
  const rowRefs = useRef(new Map<number, HTMLDivElement>());

  /* Thin rail along the top of the pane showing position in a long file.
     Driven by the pane's own scroll event rather than `useScroll`: that hook
     asserts its container ref is hydrated, and this pane does not exist at
     all while the dialog is closed. */
  const scrollProgress = useMotionValue(0);
  const railScale = useSpring(scrollProgress, { stiffness: 220, damping: 34, mass: 0.4 });

  const onPaneScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      const pane = event.currentTarget;
      const travel = pane.scrollHeight - pane.clientHeight;
      scrollProgress.set(travel > 0 ? pane.scrollTop / travel : 0);
    },
    [scrollProgress],
  );

  /* Opening a different experiment resets the pane during render rather than
     in an effect — an effect would paint the previous experiment's source for
     a frame before clearing it. */
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  if (experimentId !== null && experimentId !== loadedFor) {
    setLoadedFor(experimentId);
    setCode("");
    setResults(null);
    setTab("code");
    setQuery("");
    setCursor(0);
    setLoading(true);
  }

  useEffect(() => {
    if (!experimentId) return;
    /* A slow response for a previously opened experiment must not land on top
       of a newer one. */
    let cancelled = false;
    Promise.all([api.experimentCode(experimentId), api.experimentResults(experimentId)])
      .then(([codeBody, resultBody]) => {
        if (cancelled) return;
        setCode(codeBody.code);
        setResults(resultBody);
      })
      .catch(() => {
        if (!cancelled) setCode("# Could not load experiment code.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [experimentId]);

  const body =
    tab === "code" ? code : tab === "stdout" ? results?.stdout ?? "" : results?.stderr ?? "";
  const language: Language = tab === "code" ? "python" : "log";

  const lines = useMemo(() => highlightLines(body, language), [body, language]);

  /* Plain text per line, so find does not have to walk the token tree. */
  const plain = useMemo(
    () => lines.map((tokens) => tokens.map((token) => token.value).join("").toLowerCase()),
    [lines],
  );

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle.length === 0) return [];
    return plain.reduce<number[]>((found, text, index) => {
      if (text.includes(needle)) found.push(index);
      return found;
    }, []);
  }, [plain, query]);

  /* `cursor` is reset by whatever changed the query or the tab, so it can
     still be stale for one render if the source itself changed underneath. */
  const active = matches.length > 0 ? cursor % matches.length : -1;

  const jump = useCallback(
    (step: number) => {
      if (matches.length === 0) return;
      const next = (cursor + step + matches.length) % matches.length;
      setCursor(next);
      rowRefs.current
        .get(matches[next])
        ?.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
    },
    [cursor, matches, reduced],
  );

  function download() {
    const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = tab === "code" ? filenameFor(experimentName) : `${tab}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const searching = query.trim().length > 0;
  const hasStderr = (results?.stderr ?? "").trim().length > 0;
  const charCount = body.length;

  return (
    <Modal
      open={experimentId !== null}
      onClose={onClose}
      title={experimentName || "Experiment"}
      subtitle="Generated by the ENGINEER agent · executed in the sandbox"
      width="max-w-5xl"
    >
      {/* ----------------------------------------------------------- toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SegTabs
          value={tab}
          options={TABS}
          onChange={(next) => {
            setTab(next);
            setCursor(0);
          }}
          label="Source and output"
        />

        {hasStderr && tab !== "stderr" && (
          <button
            type="button"
            onClick={() => setTab("stderr")}
            className="mono text-[10px] text-[var(--terracotta)] hover:underline"
            title="This experiment wrote to stderr"
          >
            ! stderr
          </button>
        )}

        {/* find */}
        <div className="find-bar" data-active={searching}>
          <span className="mono text-[10px] text-[var(--bone-faint)]">find</span>
          <input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                jump(event.shiftKey ? -1 : 1);
              }
            }}
            placeholder="filter lines…"
            aria-label="Find in source"
            className="mono w-[120px] bg-transparent text-[11px] text-[var(--bone)] outline-none placeholder:text-[var(--bone-faint)]"
          />
          <AnimatePresence initial={false}>
            {searching && (
              <motion.span
                className="mono shrink-0 text-[10px]"
                style={{ color: matches.length > 0 ? "var(--teal)" : "var(--terracotta)" }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                {matches.length > 0 ? `${active + 1}/${matches.length}` : "0"}
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          {results && results.attempts > 1 && (
            <Badge tone="amber" animated>
              {results.attempts} attempts
            </Badge>
          )}
          {results && results.execution_time > 0 && tab !== "code" && (
            <Badge tone="teal">{results.execution_time.toFixed(2)}s</Badge>
          )}
          <Button onClick={() => setWrap((previous) => !previous)} title="Toggle line wrapping">
            {wrap ? "nowrap" : "wrap"}
          </Button>
          <CopyButton text={body} disabled={body.length === 0} />
          <Button onClick={download} disabled={body.length === 0} title="Download this buffer">
            save
          </Button>
        </div>
      </div>

      {/* -------------------------------------------------------------- pane */}
      <div className="code-pane recess relative">
        <motion.div
          className="code-rail"
          style={{ scaleX: railScale }}
          aria-hidden
        />

        <div onScroll={onPaneScroll} className="max-h-[56vh] overflow-auto py-2">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={`${tab}-${loading}`}
              initial={reduced ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.14 }}
            >
              {loading ? (
                <div className="space-y-2 px-4 py-3">
                  {Array.from({ length: 8 }).map((_, index) => (
                    <motion.div
                      key={index}
                      className="skeleton-line"
                      style={{ width: `${88 - index * 7}%` }}
                      animate={reduced ? undefined : { opacity: [0.28, 0.6, 0.28] }}
                      transition={{ duration: 1.3, repeat: Infinity, delay: index * 0.08 }}
                    />
                  ))}
                </div>
              ) : body.trim() === "" ? (
                <p className="mono px-4 py-3 text-[11px] text-[var(--bone-faint)]">
                  No {tab} captured for this experiment.
                </p>
              ) : (
                lines.map((tokens, index) => (
                  <div
                    key={index}
                    ref={(node) => {
                      if (node) rowRefs.current.set(index, node);
                      else rowRefs.current.delete(index);
                    }}
                  >
                    <CodeLine
                      number={index + 1}
                      tokens={tokens}
                      wrap={wrap}
                      dimmed={searching && !matches.includes(index)}
                      matched={searching && matches[active] === index}
                      animate={!reduced && index < STAGGER_LIMIT}
                      delay={Math.min(index * 0.008, 0.5)}
                    />
                  </div>
                ))
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* ------------------------------------------------------------ status */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="mono text-[10px] text-[var(--bone-faint)]">
          {tab === "code" ? "python" : "log"} · {lines.length} lines ·{" "}
          {charCount > 1024 ? `${(charCount / 1024).toFixed(1)} KB` : `${charCount} B`}
        </span>
        {results && (
          <span
            className="mono text-[10px]"
            style={{
              color: results.status === "SUCCEEDED" ? "var(--sage)" : "var(--bone-faint)",
            }}
          >
            {results.status.toLowerCase()}
          </span>
        )}
        <span className="mono ml-auto text-[10px] text-[var(--bone-faint)]">
          enter ↵ next match · esc closes
        </span>
      </div>
    </Modal>
  );
}
