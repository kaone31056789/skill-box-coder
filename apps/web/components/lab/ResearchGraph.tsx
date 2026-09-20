"use client";

import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  type Edge,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { memo, useEffect, useMemo } from "react";

import { Empty, Led } from "@/components/ui/Instrument";
import type { GraphNodeKind, ResearchGraph } from "@/lib/types";

/* Layered left-to-right layout: question -> hypothesis -> experiment -> result.
   Deterministic and dependency-free, which beats pulling in a layout engine
   for a graph this shape. */
const COLUMN: Record<GraphNodeKind, number> = {
  question: 0,
  hypothesis: 1,
  experiment: 2,
  result_success: 3,
  result_failed: 3,
};

const COL_X = [0, 300, 620, 920];
const ROW_H = 104;

const TONE: Record<GraphNodeKind, { accent: string; label: string }> = {
  question: { accent: "var(--iris)", label: "Question" },
  hypothesis: { accent: "var(--amber)", label: "Hypothesis" },
  experiment: { accent: "var(--teal)", label: "Experiment" },
  result_success: { accent: "var(--sage)", label: "Result" },
  result_failed: { accent: "var(--terracotta)", label: "Failed" },
};

interface NodePayload extends Record<string, unknown> {
  kind: GraphNodeKind;
  label: string;
  meta: Record<string, unknown>;
}

const ResearchNode = memo(function ResearchNode({ data }: NodeProps) {
  const { kind, label, meta } = data as NodePayload;
  const tone = TONE[kind];
  const isBest = meta.isBest === true;
  const isCurrent = meta.isCurrent === true;
  const metrics = (meta.metrics ?? {}) as Record<string, number>;

  return (
    <div
      className="panel relative px-3 py-2.5"
      style={{
        width: 228,
        borderColor: isBest ? "var(--sage)" : isCurrent ? "var(--teal)" : undefined,
        boxShadow: isBest
          ? "inset 0 1px 0 rgba(255,255,255,0.08), 0 0 0 1px var(--sage), 0 0 22px -4px rgba(143,174,134,0.55)"
          : isCurrent
            ? "inset 0 1px 0 rgba(255,255,255,0.08), 0 0 20px -4px rgba(111,179,173,0.55)"
            : undefined,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />

      <div className="mb-1 flex items-center gap-1.5">
        <Led on tone={isCurrent ? "teal" : isBest ? "sage" : "bone"} pulse={isCurrent} />
        <span
          className="mono text-[8.5px] uppercase tracking-[0.14em]"
          style={{ color: tone.accent }}
        >
          {tone.label}
        </span>
        {isBest && (
          <span className="mono ml-auto text-[8.5px] tracking-[0.1em] text-[var(--sage)]">
            ★ BEST
          </span>
        )}
        {isCurrent && !isBest && (
          <span className="mono ml-auto text-[8.5px] tracking-[0.1em] text-[var(--teal)]">
            RUNNING
          </span>
        )}
      </div>

      <p
        className="text-[11.5px] leading-snug text-[var(--bone)]"
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 3,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
        title={label}
      >
        {label}
      </p>

      {typeof metrics.f1 === "number" && (
        <div className="mono mt-1.5 flex gap-2.5 border-t pt-1.5 text-[9.5px] hairline">
          <span className="text-[var(--sage)]">F1 {metrics.f1.toFixed(3)}</span>
          {typeof metrics.false_positive_rate === "number" && (
            <span className="text-[var(--bone-faint)]">
              FPR {(metrics.false_positive_rate * 100).toFixed(2)}%
            </span>
          )}
        </div>
      )}

      {typeof meta.approach === "string" && kind === "experiment" && (
        <div className="mono mt-1.5 text-[9px] text-[var(--bone-faint)]">
          {meta.approach as string} · {(meta.featureSet as string) ?? "base"}
        </div>
      )}

      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
});

const nodeTypes = { research: ResearchNode };

function Canvas({
  graph,
  onSelectExperiment,
}: {
  graph: ResearchGraph;
  onSelectExperiment?: (experimentId: string) => void;
}) {
  const { fitView } = useReactFlow();

  const { nodes, edges } = useMemo(() => {
    const rowCursor = [0, 0, 0, 0];
    const layoutNodes: Node[] = graph.nodes.map((node) => {
      const column = COLUMN[node.kind];
      const row = rowCursor[column];
      rowCursor[column] += 1;
      return {
        id: node.id,
        type: "research",
        position: { x: COL_X[column], y: row * ROW_H },
        data: { kind: node.kind, label: node.label, meta: node.data },
        draggable: true,
      };
    });

    const layoutEdges: Edge[] = graph.edges.map((edge) => {
      const isImprovement = edge.relation === "improved_from";
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "smoothstep",
        animated: isImprovement,
        label: edge.relation.replace(/_/g, " "),
        labelStyle: {
          fill: "var(--bone-faint)",
          fontSize: 8.5,
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        },
        labelBgStyle: { fill: "#111a1d", fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        style: {
          stroke: isImprovement ? "var(--sage)" : "rgba(151,163,161,0.32)",
          strokeWidth: isImprovement ? 2 : 1.4,
        },
      };
    });

    return { nodes: layoutNodes, edges: layoutEdges };
  }, [graph]);

  // Re-frame as the graph grows so new nodes stay on screen.
  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: 0.18, duration: 420 }), 90);
    return () => clearTimeout(timer);
  }, [nodes.length, fitView]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      fitView
      minZoom={0.15}
      maxZoom={1.6}
      proOptions={{ hideAttribution: true }}
      nodesConnectable={false}
      edgesFocusable={false}
      onNodeClick={(_event, node) => {
        // Experiment and result nodes both stand for one experiment.
        const match = /^[er]-(.+)$/.exec(node.id);
        if (match && onSelectExperiment) onSelectExperiment(match[1]);
      }}
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={22}
        size={1}
        color="rgba(151,163,161,0.13)"
      />
      <Controls showInteractive={false} position="bottom-right" />
    </ReactFlow>
  );
}

export function ResearchGraphView({
  graph,
  onSelectExperiment,
}: {
  graph: ResearchGraph | null;
  onSelectExperiment?: (experimentId: string) => void;
}) {
  if (!graph || graph.nodes.length === 0) {
    return <Empty>The research graph builds itself as GENESIS works. Start a run to populate it.</Empty>;
  }
  return (
    <ReactFlowProvider>
      <Canvas graph={graph} onSelectExperiment={onSelectExperiment} />
    </ReactFlowProvider>
  );
}
