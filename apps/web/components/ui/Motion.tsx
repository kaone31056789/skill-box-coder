"use client";

/**
 * Motion primitives for the console.
 *
 * The dashboard watches a process that can sit silent for a minute at a time,
 * so motion here is load-bearing rather than decorative: numbers count to
 * their new value so a change is impossible to miss, meters spring rather
 * than jump, and anything in flight keeps moving. Every primitive collapses
 * to a static state under `prefers-reduced-motion`.
 */
import {
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useSpring,
  type Transition,
} from "motion/react";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

export const EASE_OUT: Transition = {
  duration: 0.42,
  ease: [0.2, 0.8, 0.3, 1],
};

const COUNT_SPRING = { stiffness: 130, damping: 22, mass: 0.55, restDelta: 0.0001 };

/**
 * A number that travels to its new value instead of snapping.
 *
 * Text is written straight to the DOM node from the spring subscription: at
 * 60fps a `setState` per frame would re-render the whole readout tree.
 */
export function AnimatedNumber({
  value,
  format,
  className = "",
  style,
  flash = true,
}: {
  value: number;
  format: (value: number) => string;
  className?: string;
  style?: CSSProperties;
  /** Briefly lift the glow when the value settles somewhere new. */
  flash?: boolean;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  /* Latest-ref, so the spring subscription never has to re-bind when a caller
     passes a fresh inline formatter on every render. */
  const formatRef = useRef(format);
  useEffect(() => {
    formatRef.current = format;
  });

  const source = useMotionValue(value);
  const spring = useSpring(source, COUNT_SPRING);
  const previous = useRef(value);

  useEffect(() => {
    if (reduced) {
      spring.jump(value);
    } else {
      source.set(value);
    }
    if (flash && !reduced && previous.current !== value && ref.current) {
      const node = ref.current;
      node.getAnimations().forEach((animation) => animation.cancel());
      node.animate(
        [{ filter: "brightness(1)" }, { filter: "brightness(1.6)" }, { filter: "brightness(1)" }],
        { duration: 720, easing: "ease-out" },
      );
    }
    previous.current = value;
  }, [value, reduced, flash, source, spring]);

  useEffect(() => {
    const write = (next: number) => {
      if (ref.current) ref.current.textContent = formatRef.current(next);
    };
    write(spring.get());
    return spring.on("change", write);
  }, [spring]);

  return (
    <span ref={ref} className={className} style={style}>
      {format(value)}
    </span>
  );
}

/** Fade-and-rise on mount. The workhorse for panel content. */
export function Reveal({
  children,
  delay = 0,
  y = 8,
  className = "",
  style,
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      style={style}
      initial={reduced ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...EASE_OUT, delay: reduced ? 0 : delay }}
    >
      {children}
    </motion.div>
  );
}

/** Same, but held until the element scrolls into its scroll container. */
export function RevealOnView({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.2 });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial={reduced ? false : { opacity: 0, y: 10 }}
      animate={inView || reduced ? { opacity: 1, y: 0 } : undefined}
      transition={{ ...EASE_OUT, delay: reduced ? 0 : delay }}
    >
      {children}
    </motion.div>
  );
}

/** Container that cascades its `StaggerItem` children. */
export function Stagger({
  children,
  className = "",
  gap = 0.045,
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  gap?: number;
  delay?: number;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduced ? false : "hidden"}
      animate="shown"
      variants={{
        hidden: {},
        shown: { transition: { staggerChildren: gap, delayChildren: delay } },
      }}
    >
      {children}
    </motion.div>
  );
}

const ITEM_VARIANTS = {
  hidden: { opacity: 0, y: 10 },
  shown: { opacity: 1, y: 0, transition: EASE_OUT },
};

export function StaggerItem({
  children,
  className = "",
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <motion.div className={className} style={style} variants={ITEM_VARIANTS}>
      {children}
    </motion.div>
  );
}

/**
 * Circular progress. Used in the header, where a bar would not fit but the
 * "how far through the plan are we" question still needs an answer.
 */
export function ProgressRing({
  value,
  size = 30,
  stroke = 3,
  color = "var(--sage)",
  track = "rgba(230,224,211,0.09)",
  children,
}: {
  value: number;
  size?: number;
  stroke?: number;
  color?: string;
  track?: string;
  children?: ReactNode;
}) {
  const reduced = useReducedMotion();
  const clamped = Math.max(0, Math.min(1, value));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <span
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={track}
          strokeWidth={stroke}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          initial={false}
          animate={{ strokeDashoffset: circumference * (1 - clamped) }}
          transition={reduced ? { duration: 0 } : { type: "spring", stiffness: 90, damping: 20 }}
          style={{ filter: `drop-shadow(0 0 4px ${color}66)` }}
        />
      </svg>
      {children && (
        <span className="absolute inset-0 flex items-center justify-center">{children}</span>
      )}
    </span>
  );
}

/**
 * Metric trend across experiments. Deliberately unlabelled — it answers
 * "is this run getting better?" at a glance; the table answers the rest.
 */
export function Sparkline({
  values,
  width = 96,
  height = 26,
  color = "var(--sage)",
  highlightLast = true,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  highlightLast?: boolean;
}) {
  const reduced = useReducedMotion();
  /* A single reading has no trend to draw — one floating dot beside the
     figure reads as a rendering artefact, not as data. */
  if (values.length < 2) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pad = 3;
  const stepX = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;

  const points: [number, number][] = values.map((value, index) => [
    pad + index * stepX,
    height - pad - ((value - min) / span) * (height - pad * 2),
  ]);

  const path = points
    .map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const last = points[points.length - 1];
  const area = `${path} L${last[0].toFixed(1)},${height} L${points[0][0].toFixed(1)},${height} Z`;
  const gradientId = `spark-${color.replace(/[^a-z]/gi, "")}-${values.length}`;

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.26" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <motion.path
        d={area}
        fill={`url(#${gradientId})`}
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.25 }}
      />
      <motion.path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={reduced ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      />
      {highlightLast && (
        <motion.circle
          cx={last[0]}
          cy={last[1]}
          r={2.4}
          fill={color}
          initial={reduced ? false : { scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 300, damping: 16, delay: 0.55 }}
          style={{ filter: `drop-shadow(0 0 4px ${color})` }}
        />
      )}
    </svg>
  );
}

/** mm:ss since a timestamp. Proof the run is still alive during long calls. */
export function useElapsed(since: string | null | undefined, running: boolean): string {
  const [label, setLabel] = useState("00:00");

  useEffect(() => {
    if (!since) return;
    const started = new Date(since).getTime();
    if (Number.isNaN(started)) return;

    const pad = (n: number) => String(n).padStart(2, "0");
    const tick = () => {
      const total = Math.max(0, Math.floor((Date.now() - started) / 1000));
      const hours = Math.floor(total / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const seconds = total % 60;
      setLabel(
        hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`,
      );
    };

    tick();
    if (!running) return;
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [since, running]);

  return label;
}

/** Soft radar sweep behind a live indicator — the console's heartbeat. */
export function Pulse({ color = "var(--teal)", size = 7 }: { color?: string; size?: number }) {
  const reduced = useReducedMotion();
  return (
    <span className="relative inline-flex" style={{ width: size, height: size }} aria-hidden>
      <span className="absolute inset-0 rounded-full" style={{ background: color }} />
      {!reduced && (
        <motion.span
          className="absolute inset-0 rounded-full"
          style={{ background: color }}
          animate={{ scale: [1, 2.6], opacity: [0.55, 0] }}
          transition={{ duration: 1.8, repeat: Infinity, ease: "easeOut" }}
        />
      )}
    </span>
  );
}
