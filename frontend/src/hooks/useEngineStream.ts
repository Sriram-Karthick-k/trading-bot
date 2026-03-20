/**
 * WebSocket hook for real-time engine events, status, and data updates.
 *
 * Connects to the /api/ws/ticks/{clientId} endpoint and sends
 * "subscribe_engine" to receive engine_event, engine_status, and
 * data push messages (orders_update, risk_update).
 *
 * When data updates arrive, they are injected into the SWR cache via
 * mutate() so all components using SWR hooks see fresh data immediately
 * without polling.
 *
 * SWR hooks still poll at long intervals (10s) as fallback for:
 * - Initial page load (before WS connects)
 * - WS reconnection gaps
 */

import { useEffect, useRef, useCallback, useState, useMemo } from "react";
import { mutate } from "swr";
import type { EngineEvent, EngineStatus } from "@/types";

const MAX_EVENTS = 100;

/** How long to wait before reconnecting (ms). */
const RECONNECT_DELAY = 3000;

/** How often to send a ping keepalive (ms). */
const PING_INTERVAL = 30000;

interface UseEngineStreamOptions {
  /** Enable/disable the stream. Defaults to true. */
  enabled?: boolean;
  /** Max events to keep in buffer. Defaults to 100. */
  maxEvents?: number;
}

interface UseEngineStreamReturn {
  /** Whether the WebSocket is connected and engine-subscribed. */
  connected: boolean;
  /** Latest engine status snapshot received via WebSocket. */
  status: EngineStatus | null;
  /** Buffer of engine events received via WebSocket (newest last). */
  events: EngineEvent[];
  /** Manually clear the event buffer. */
  clearEvents: () => void;
}

/**
 * Map of WebSocket data_type → SWR cache key.
 * When we receive a broadcast of this type, we inject the data into SWR.
 */
const WS_TO_SWR_KEY: Record<string, string> = {
  orders_update: "orders",
  risk_update: "risk-status",
};

export function useEngineStream(
  options: UseEngineStreamOptions = {},
): UseEngineStreamReturn {
  const { enabled = true, maxEvents = MAX_EVENTS } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [events, setEvents] = useState<EngineEvent[]>([]);

  const clearEvents = useCallback(() => setEvents([]), []);

  // Stable client ID for this tab session
  const clientId = useMemo(
    () => `engine_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    [],
  );

  const cleanup = useCallback(() => {
    if (pingRef.current) {
      clearInterval(pingRef.current);
      pingRef.current = null;
    }
    if (reconnectRef.current) {
      clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onclose = null; // prevent reconnect on intentional close
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (!enabled || !mountedRef.current) return;

    // Clean up any existing connection
    cleanup();

    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || "wss://localhost:8000";
    const ws = new WebSocket(`${wsUrl}/api/ws/ticks/${clientId}`);

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close();
        return;
      }

      // Subscribe to engine events
      ws.send(JSON.stringify({ action: "subscribe_engine" }));

      // Start keepalive pings
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ action: "ping" }));
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current) return;

      try {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case "engine_subscribed":
            setConnected(true);
            break;

          case "engine_event": {
            const evt = data.event;
            if (!evt) break;
            const engineEvent: EngineEvent = {
              timestamp: evt.timestamp,
              type: evt.type ?? "info",
              message: evt.message ?? "",
              data: evt.data ?? {},
            };
            setEvents((prev) => {
              const next = [...prev, engineEvent];
              return next.length > maxEvents ? next.slice(-maxEvents) : next;
            });
            break;
          }

          case "engine_status": {
            const statusPayload = data.status;
            if (statusPayload) {
              setStatus(statusPayload as EngineStatus);
              // Also inject into SWR cache so useEngineStatus() picks it up
              mutate("engine-status", statusPayload, false);
            }
            break;
          }

          case "tick":
            // Tick data — ignore in this hook (handled by useTickStream)
            break;

          case "pong":
            // Keepalive response — no action needed
            break;

          default: {
            // Handle data push messages (orders_update, risk_update, etc.)
            const swrKey = WS_TO_SWR_KEY[data.type];
            if (swrKey && data.data !== undefined) {
              // Inject received data into SWR cache without revalidation
              mutate(swrKey, data.data, false);
            }
            break;
          }
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);

      // Auto-reconnect
      reconnectRef.current = setTimeout(() => {
        if (mountedRef.current && enabled) {
          connect();
        }
      }, RECONNECT_DELAY);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, which handles reconnect
      setConnected(false);
    };

    wsRef.current = ws;
  }, [clientId, enabled, maxEvents, cleanup]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [connect, cleanup]);

  return { connected, status, events, clearEvents };
}
