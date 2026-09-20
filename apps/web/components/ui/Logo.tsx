/**
 * GENESIS mark.
 *
 * The identity is the closed research loop, so the mark *is* the loop: an
 * orbit broken at one point (research is never quite closed), carrying the
 * four stages as nodes. The filled node is the discovery — the one result
 * that came back measured. It reads at 16px as a favicon and at 200px as a
 * hero mark, and needs no text to make sense.
 */
export function Logo({
  size = 28,
  className = "",
  animated = false,
}: {
  size?: number;
  className?: string;
  animated?: boolean;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      role="img"
      aria-label="GENESIS"
    >
      <defs>
        <linearGradient id="genesis-orbit" x1="0" y1="0" x2="48" y2="48">
          <stop offset="0%" stopColor="#6fb3ad" />
          <stop offset="55%" stopColor="#8fae86" />
          <stop offset="100%" stopColor="#d9a441" />
        </linearGradient>
        <filter id="genesis-glow" x="-70%" y="-70%" width="240%" height="240%">
          <feGaussianBlur stdDeviation="1.6" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* The loop, broken at the top-right: an open question. */}
      <circle
        cx="24"
        cy="24"
        r="16"
        stroke="url(#genesis-orbit)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeDasharray="76 24"
        transform="rotate(-58 24 24)"
        opacity="0.95"
      >
        {animated && (
          <animateTransform
            attributeName="transform"
            type="rotate"
            from="-58 24 24"
            to="302 24 24"
            dur="9s"
            repeatCount="indefinite"
          />
        )}
      </circle>

      {/* Stage nodes around the loop. */}
      <circle cx="24" cy="8" r="2.6" fill="#6fb3ad" />
      <circle cx="40" cy="24" r="2.6" fill="#8fae86" />
      <circle cx="24" cy="40" r="2.6" fill="#d9a441" />
      <circle cx="8" cy="24" r="2.6" fill="#8f8ab8" />

      {/* The discovery: the one node that came back measured. */}
      <circle cx="24" cy="24" r="5" fill="#e6e0d3" filter="url(#genesis-glow)" />
      <circle cx="24" cy="24" r="8.5" stroke="#e6e0d3" strokeWidth="0.9" opacity="0.28" />
    </svg>
  );
}

/** Mark plus wordmark, for headers. */
export function Wordmark({
  size = 26,
  subtitle,
  animated = false,
}: {
  size?: number;
  subtitle?: string;
  animated?: boolean;
}) {
  return (
    <span className="flex items-center gap-2.5">
      <Logo size={size} animated={animated} />
      <span className="flex items-baseline gap-2.5">
        <span
          className="display leading-none tracking-[0.13em] text-[var(--bone)]"
          style={{ fontSize: size * 0.78 }}
        >
          GENESIS
        </span>
        {subtitle && (
          <span className="label hidden !text-[8.5px] !tracking-[0.3em] sm:inline">
            {subtitle}
          </span>
        )}
      </span>
    </span>
  );
}
