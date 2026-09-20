"use client";

/**
 * Shared instrument-panel primitives.
 *
 * These carry the skeuomorphic language of the console: machined plates with
 * corner screws, recessed readouts, indicator lamps and engraved labels.
 * Anything that shows a changing value moves to its new state rather than
 * cutting, so an operator glancing back at the console can see what changed.
 */
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { AnimatedNumber } from "@/components/ui/Motion";

type Tone = "teal" | "sage" | "amber" | "terracotta" | "iris" | "bone";

const TONE_VAR: Record<Tone, string> = {
  teal: "var(--teal)",
  sage: "var(--sage)",
  amber: "var(--amber)",
  terracotta: "var(--terracotta)",
  iris: "var(--iris)",
  bone: "var(--bone-dim)",
};

export function Led({
  on = false,
  tone = "teal",
  pulse = false,
}: {
  on?: boolean;
  tone?: Tone;
  pulse?: boolean;
}) {
  return (
    <span
      className="led"
      data-on={on}
      data-pulse={pulse && on}
      style={{ ["--led-color" as string]: TONE_VAR[tone] }}
      aria-hidden
    />
  );
}

export function Screws() {
  return (
    <>
      <span className="screw" style={{ top: 6, left: 6 }} aria-hidden />
      <span className="screw" style={{ top: 6, right: 6 }} aria-hidden />
      <span className="screw" style={{ bottom: 6, left: 6 }} aria-hidden />
      <span className="screw" style={{ bottom: 6, right: 6 }} aria-hidden />
    </>
  );
}

export function Panel({
  title,
  right,
  children,
  className = "",
  screws = false,
  bodyClassName = "",
  /** Stagger index, so a column of panels settles in sequence on load. */
  delay = 0,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  screws?: boolean;
  bodyClassName?: string;
  delay?: number;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.section
      className={`panel flex flex-col ${className}`}
      initial={reduced ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: reduced ? 0 : delay, ease: [0.2, 0.8, 0.3, 1] }}
    >
      {screws && <Screws />}
      {title && (
        <header className="flex items-center justify-between gap-3 border-b px-4 py-2.5 hairline shrink-0">
          <h2 className="label engraved">{title}</h2>
          {right}
        </header>
      )}
      <div className={`relative flex-1 min-h-0 ${bodyClassName}`}>{children}</div>
    </motion.section>
  );
}

/**
 * A recessed numeric readout — the console's primary way of showing a value.
 *
 * The number counts to its new reading and the delta chip swaps in behind it,
 * which is how a metric moving mid-run reads as an event rather than a
 * silently different string.
 */
export function Readout({
  label,
  value,
  format = (v) => String(v),
  unit,
  tone = "bone",
  delta,
  size = "md",
  footer,
}: {
  label: string;
  value: number;
  format?: (value: number) => string;
  unit?: string;
  tone?: Tone;
  delta?: { value: string; good: boolean } | null;
  size?: "sm" | "md" | "lg";
  footer?: ReactNode;
}) {
  const textSize = size === "lg" ? "text-3xl" : size === "sm" ? "text-lg" : "text-2xl";
  return (
    <div className="readout px-3 py-2.5">
      <div className="label mb-1">{label}</div>
      <div className="flex items-baseline gap-1.5">
        <AnimatedNumber
          value={value}
          format={format}
          className={`mono font-medium ${textSize}`}
          style={{ color: TONE_VAR[tone], textShadow: `0 0 14px ${TONE_VAR[tone]}55` }}
        />
        {unit && <span className="mono text-[11px] text-[var(--bone-faint)]">{unit}</span>}
        <AnimatePresence mode="wait" initial={false}>
          {delta && (
            <motion.span
              key={delta.value}
              className="mono ml-auto text-[11px]"
              style={{ color: delta.good ? "var(--sage)" : "var(--terracotta)" }}
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.28 }}
            >
              {delta.value}
            </motion.span>
          )}
        </AnimatePresence>
      </div>
      {footer && <div className="mt-1.5">{footer}</div>}
    </div>
  );
}

/** Horizontal bar meter with a machined channel and lit fill. */
export function Meter({
  value,
  tone = "teal",
  height = 6,
  /** Adds a travelling highlight, for a meter that is still filling. */
  live = false,
}: {
  value: number;
  tone?: Tone;
  height?: number;
  live?: boolean;
}) {
  const reduced = useReducedMotion();
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className="recess relative w-full overflow-hidden"
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <motion.div
        className="relative h-full rounded-[3px]"
        initial={false}
        animate={{ width: `${pct}%` }}
        transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 120, damping: 22 }}
        style={{
          background: `linear-gradient(90deg, ${TONE_VAR[tone]}99, ${TONE_VAR[tone]})`,
          boxShadow: `0 0 10px ${TONE_VAR[tone]}88`,
        }}
      />
      {live && !reduced && pct > 0 && pct < 100 && (
        <motion.span
          className="pointer-events-none absolute inset-y-0 w-8"
          style={{
            background: `linear-gradient(90deg, transparent, ${TONE_VAR[tone]}, transparent)`,
            opacity: 0.5,
          }}
          /* Both keyframes are percentages of this element's own width —
             mixing px and % in one keyframe list has no valid interpolation. */
          animate={{ x: ["-100%", "900%"] }}
          transition={{ duration: 1.9, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden
        />
      )}
    </div>
  );
}

export function Badge({
  children,
  tone = "bone",
  /** Pop in on first paint — used where a badge appears mid-run. */
  animated = false,
}: {
  children: ReactNode;
  tone?: Tone;
  animated?: boolean;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.span
      className="mono inline-flex items-center rounded-[3px] border px-1.5 py-0.5 text-[9.5px] uppercase tracking-[0.1em]"
      initial={animated && !reduced ? { opacity: 0, scale: 0.8 } : false}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: "spring", stiffness: 420, damping: 24 }}
      style={{
        color: TONE_VAR[tone],
        borderColor: `${TONE_VAR[tone]}44`,
        background: `${TONE_VAR[tone]}12`,
      }}
    >
      {children}
    </motion.span>
  );
}

/**
 * Segmented control with a pill that slides between options.
 *
 * The shared `layoutId` is what makes the selection travel: React swaps which
 * button owns the pill and Motion interpolates between the two positions.
 */
export function SegTabs<T extends string>({
  value,
  options,
  onChange,
  className = "",
  label,
}: {
  value: T;
  options: readonly { key: T; label: ReactNode }[];
  onChange: (key: T) => void;
  className?: string;
  label?: string;
}) {
  const groupId = useId();
  const reduced = useReducedMotion();
  return (
    <div className={`seg ${className}`} data-animated="true" role="group" aria-label={label}>
      {options.map((option) => {
        const selected = option.key === value;
        return (
          <button
            key={option.key}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option.key)}
          >
            {selected && (
              <motion.span
                layoutId={`seg-pill-${groupId}`}
                className="seg-pill"
                transition={
                  reduced ? { duration: 0 } : { type: "spring", stiffness: 420, damping: 34 }
                }
                aria-hidden
              />
            )}
            <span className="seg-text">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  loading = false,
  variant,
  title,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "danger";
  title?: string;
  className?: string;
}) {
  const rippleRef = useRef<HTMLSpanElement>(null);
  return (
    <motion.button
      type="button"
      className={`btn ${className}`}
      data-variant={variant}
      whileHover={disabled || loading ? undefined : { y: -1 }}
      whileTap={disabled || loading ? undefined : { y: 1, scale: 0.98 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      onClick={(event) => {
        const ripple = rippleRef.current;
        if (ripple && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          const rect = event.currentTarget.getBoundingClientRect();
          const size = Math.hypot(rect.width, rect.height) * 2;
          const x = event.detail === 0 ? rect.width / 2 : event.clientX - rect.left;
          const y = event.detail === 0 ? rect.height / 2 : event.clientY - rect.top;
          ripple.getAnimations().forEach((animation) => animation.cancel());
          Object.assign(ripple.style, {
            width: `${size}px`,
            height: `${size}px`,
            left: `${x}px`,
            top: `${y}px`,
          });
          ripple.animate(
            [
              { transform: "translate(-50%, -50%) scale(0)", opacity: 0.22 },
              { transform: "translate(-50%, -50%) scale(1)", opacity: 0 },
            ],
            { duration: 550, easing: "ease-out" },
          );
        }
        onClick?.();
      }}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      title={title}
    >
      <span ref={rippleRef} className="button-ripple" aria-hidden="true" />
      {loading && <span className="button-spinner" aria-hidden="true" />}
      {children}
    </motion.button>
  );
}

/**
 * Modal with a scaled entrance and a real exit.
 *
 * `AnimatePresence` keeps the panel mounted long enough to animate out, and
 * Escape closes it — a dialog that can only be dismissed by clicking the
 * backdrop is a trap for anyone on a keyboard.
 */
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = "max-w-4xl",
  toolbar,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  width?: string;
  /** Controls that belong to the dialog itself, beside the close button. */
  toolbar?: ReactNode;
}) {
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-6"
          /* The blur is static: an animated `backdropFilter` can leave this
             overlay's exit animation unresolved, and an un-unmounted
             full-screen backdrop at opacity 0 eats every click on the page. */
          /* And while exiting it stops taking pointer events at all, so even a
             stalled animation can never leave the page unclickable. */
          style={{
            background: "rgba(6,10,11,0.78)",
            backdropFilter: "blur(4px)",
            pointerEvents: open ? "auto" : "none",
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onClick={onClose}
          role="dialog"
          aria-modal="true"
          aria-label={title}
        >
          <motion.div
            className={`panel flex max-h-[86vh] w-full flex-col ${width}`}
            initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: 14 }}
            animate={{
              opacity: 1,
              scale: 1,
              y: 0,
              transition: reduced
                ? { duration: 0.12 }
                : { type: "spring", stiffness: 300, damping: 28, mass: 0.7 },
            }}
            /* Exit is a bounded tween, never a spring: AnimatePresence holds
               the backdrop mounted until every child animation resolves. */
            exit={{
              opacity: 0,
              scale: reduced ? 1 : 0.97,
              y: reduced ? 0 : 8,
              transition: { duration: 0.15, ease: "easeIn" },
            }}
            onClick={(event) => event.stopPropagation()}
          >
            <Screws />
            <header className="flex items-start justify-between gap-4 border-b px-5 py-3.5 hairline">
              <div className="min-w-0">
                <h2 className="display text-[19px] leading-tight text-[var(--bone)]">{title}</h2>
                {subtitle && (
                  <p className="mono mt-0.5 truncate text-[11px] text-[var(--bone-faint)]">
                    {subtitle}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {toolbar}
                <Button onClick={onClose} title="Close (Esc)">
                  Close
                </Button>
              </div>
            </header>
            <div className="min-h-0 flex-1 overflow-auto p-5">{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className="flex h-full items-center justify-center p-6 text-center"
      initial={reduced ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
    >
      <p className="mono max-w-[30ch] text-[11px] leading-relaxed text-[var(--bone-faint)]">
        {children}
      </p>
    </motion.div>
  );
}
