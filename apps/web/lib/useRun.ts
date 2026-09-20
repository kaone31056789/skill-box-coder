"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, socketUrl } from "./api";
import type {
  AgentEvent,
  Comparison,
  ResearchGraph,
  RunDetail,
  RunState,
  SocketMessage,
} from "./types";

const MAX_EVENTS = 300;
const RECONNECT_MS = 2000;

interface UseRunResult {
  run: RunDetail | null;
  events: AgentEvent[];
  graph: ResearchGraph | null;
  comparison: Comparison | null;
  /** Live stdout per experiment id, streamed while the sandbox runs. */
  output: Record<string, string[]>;
  state: RunState;
  connected: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Live view of a research run.
 *
 * The WebSocket carries the fast path (agent events, state transitions). Any
 * structural change — a new node, a new metric — arrives as a `graph_update`
 * nudge, and we re-fetch the authoritative record over REST. That keeps the
 * socket payloads small and the DB the single source of truth.
 */
export function useRun(runId: string | null): UseRunResult {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [graph, setGraph] = useState<ResearchGraph | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [output, setOutput] = useState<Record<string, string[]>>({});
  const [state, setState] = useState<RunState>("CREATED");
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);
  // Coalesces bursts of graph_update nudges into a single refetch.
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const [detail, nextGraph, nextComparison] = await Promise.all([
        api.getRun(runId),
        api.graph(runId),
        api.comparison(runId),
      ]);
      setRun(detail);
      setGraph(nextGraph);
      setComparison(nextComparison);
      setState(detail.state);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load research run");
    }
  }, [runId]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    refreshTimerRef.current = setTimeout(() => void refresh(), 250);
  }, [refresh]);

  useEffect(() => {
    if (!runId) return;
    void refresh();
  }, [runId, refresh]);

  useEffect(() => {
    if (!runId) return;
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;
      const socket = new WebSocket(socketUrl(runId));
      socketRef.current = socket;

      socket.onopen = () => setConnected(true);

      socket.onmessage = (raw) => {
        let message: SocketMessage;
        try {
          message = JSON.parse(raw.data as string) as SocketMessage;
        } catch {
          return;
        }

        switch (message.type) {
          case "snapshot":
            setEvents(message.events);
            setState(message.state);
            break;
          case "agent_event": {
            const { type: _type, ...event } = message;
            setEvents((prev) => {
              // The snapshot and the live stream can overlap on reconnect.
              if (prev.some((e) => e.seq === event.seq && e.seq !== 0)) return prev;
              return [...prev, event as AgentEvent].slice(-MAX_EVENTS);
            });
            if (event.meta && "metrics" in (event.meta as object)) scheduleRefresh();
            break;
          }
          case "state":
            setState(message.state);
            scheduleRefresh();
            break;
          case "experiment_output":
            setOutput((prev) => {
              const lines = prev[message.experiment_id] ?? [];
              // Cap per experiment: a chatty simulation must not grow forever.
              return {
                ...prev,
                [message.experiment_id]: [...lines, message.line].slice(-400),
              };
            });
            break;
          case "graph_update":
            scheduleRefresh();
            break;
          case "complete":
            setState("COMPLETED");
            scheduleRefresh();
            break;
          case "error":
            setError(message.message);
            break;
          default:
            break;
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (!closedRef.current) {
          reconnectRef.current = setTimeout(connect, RECONNECT_MS);
        }
      };

      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      closedRef.current = true;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
      socketRef.current?.close();
    };
  }, [runId, scheduleRefresh]);

  return { run, events, graph, comparison, output, state, connected, error, refresh };
}
