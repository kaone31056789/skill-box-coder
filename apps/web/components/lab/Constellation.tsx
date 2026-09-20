"use client";

/**
 * Ambient research-graph motif for the landing page.
 *
 * A miniature of the real thing — question, hypotheses, experiments, a result —
 * drawing itself once on load. Deterministic geometry, no randomness, so the
 * composition is the same every visit.
 */
const NODES = [
  { x: 22, y: 96, r: 5.5, tone: "var(--iris)", delay: 0 },
  { x: 104, y: 44, r: 4, tone: "var(--amber)", delay: 0.45 },
  { x: 104, y: 96, r: 4, tone: "var(--amber)", delay: 0.6 },
  { x: 104, y: 148, r: 4, tone: "var(--amber)", delay: 0.75 },
  { x: 196, y: 70, r: 4.5, tone: "var(--teal)", delay: 1.15 },
  { x: 196, y: 132, r: 4.5, tone: "var(--teal)", delay: 1.3 },
  { x: 286, y: 100, r: 7, tone: "var(--sage)", delay: 1.75 },
] as const;

const EDGES = [
  [0, 1, 0.25],
  [0, 2, 0.35],
  [0, 3, 0.45],
  [1, 4, 0.95],
  [2, 4, 1.05],
  [3, 5, 1.15],
  [4, 6, 1.55],
  [5, 6, 1.65],
] as const;

export function Constellation() {
  return (
    <svg
      viewBox="0 0 320 200"
      className="h-auto w-full"
      role="img"
      aria-label="A research graph: one question branching into hypotheses, experiments and a result"
    >
      <defs>
        <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="3.2" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {EDGES.map(([from, to, delay], index) => {
        const a = NODES[from];
        const b = NODES[to];
        const midX = (a.x + b.x) / 2;
        return (
          <path
            key={index}
            d={`M ${a.x} ${a.y} C ${midX} ${a.y}, ${midX} ${b.y}, ${b.x} ${b.y}`}
            fill="none"
            stroke="rgba(151,163,161,0.34)"
            strokeWidth="1"
            strokeDasharray="240"
            strokeDashoffset="240"
            style={{
              animation: `draw 1.1s ease-out ${delay}s forwards`,
            }}
          />
        );
      })}

      {NODES.map((node, index) => (
        <g key={index} style={{ animation: `pop 0.5s ease-out ${node.delay}s both` }}>
          <circle
            cx={node.x}
            cy={node.y}
            r={node.r}
            fill={node.tone}
            filter="url(#glow)"
            opacity={0.92}
          />
          <circle cx={node.x} cy={node.y} r={node.r + 5} fill="none" stroke={node.tone} strokeWidth="0.6" opacity={0.24} />
        </g>
      ))}

      <style>{`
        @keyframes draw { to { stroke-dashoffset: 0; } }
        @keyframes pop {
          from { opacity: 0; transform: scale(0.4); }
          to   { opacity: 1; transform: scale(1); }
        }
        g { transform-box: fill-box; transform-origin: center; }
        @media (prefers-reduced-motion: reduce) {
          path { stroke-dashoffset: 0 !important; animation: none !important; }
          g { animation: none !important; }
        }
      `}</style>
    </svg>
  );
}
