/**
 * WebSocket hook for real-time tick data.
 */

import { useEffect, useRef, useCallback, useState } from "react";

interface TickMessage {
  instrument_token: number;
  last_price: number;
  volume?: number;
  timestamp?: string;
}

interface UseTickStreamOptions {
  clientId: string;
  tokens: number[];
  onTick?: (tick: TickMessage) => void;
  enabled?: boolean;
}

export function useTickStream({ clientId, tokens, onTick, enabled = true }: UseTickStreamOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    if (!enabled) return;

    // Auto-detect WebSocket protocol from page protocol
    const envWsUrl = process.env.NEXT_PUBLIC_WS_URL;
    let wsUrl: string;
    if (envWsUrl) {
      wsUrl = envWsUrl;
    } else if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${proto}//localhost:8000`;
    } else {
      wsUrl = "ws://localhost:8000";
    }
    const ws = new WebSocket(`${wsUrl}/api/ws/ticks/${clientId}`);

    ws.onopen = () => {
      setConnected(true);
      if (tokens.length > 0) {
        ws.send(JSON.stringify({ action: "subscribe", tokens }));
      }
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.instrument_token && onTick) {
        onTick(data);
      }
    };

    ws.onclose = () => {
      setConnected(false);
    };

    ws.onerror = () => {
      setConnected(false);
    };

    wsRef.current = ws;
  }, [clientId, enabled, tokens, onTick]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  const subscribe = useCallback((newTokens: number[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", tokens: newTokens }));
    }
  }, []);

  const unsubscribe = useCallback((removeTokens: number[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "unsubscribe", tokens: removeTokens }));
    }
  }, []);

  return { connected, subscribe, unsubscribe };
}
