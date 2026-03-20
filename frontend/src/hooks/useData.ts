/**
 * SWR-based data fetching hooks.
 *
 * Global SWR config (in swr-provider.tsx) sets:
 *   revalidateOnFocus: false, revalidateOnReconnect: false, dedupingInterval: 5000
 *
 * Hooks marked "WS-backed" use long polling intervals because the WebSocket
 * stream (useEngineStream) pushes real-time updates. Polling here is a fallback
 * for reconnection / initial load only.
 */

import useSWR from "swr";
import { orders, portfolio, strategies, config, providers, mock, engine } from "@/lib/api";
import type {
  Order,
  Position,
  Holding,
  Margins,
  StrategySnapshot,
  RiskStatus,
  RiskLimits,
  ProviderInfo,
  MockSessionStatus,
  EngineStatus,
  EnginePick,
  EngineEvent,
} from "@/types";

const fetcher = <T>(fn: () => Promise<T>) => fn();

/** WS-backed: real-time updates via WebSocket, polling as fallback. */
export function useOrders() {
  return useSWR<Order[]>("orders", () => fetcher(orders.getAll), {
    refreshInterval: 10000,
  });
}

/** WS-backed: real-time updates via WebSocket, polling as fallback. */
export function usePositions() {
  return useSWR<{ net: Position[]; day: Position[] }>(
    "positions",
    () => fetcher(portfolio.getPositions),
    { refreshInterval: 10000 },
  );
}

/** External data — not WS-backed, polls directly. */
export function useHoldings() {
  return useSWR<Holding[]>("holdings", () => fetcher(portfolio.getHoldings), {
    refreshInterval: 10000,
  });
}

/** External data — not WS-backed, polls directly. */
export function useMargins() {
  return useSWR<Margins>("margins", () => fetcher(portfolio.getMargins), {
    refreshInterval: 5000,
  });
}

/** WS-backed: real-time updates via WebSocket, polling as fallback. */
export function useStrategies() {
  return useSWR<StrategySnapshot[]>(
    "strategies",
    () => fetcher(strategies.list),
    { refreshInterval: 10000 },
  );
}

/** WS-backed: real-time updates via WebSocket, polling as fallback. */
export function useRiskStatus() {
  return useSWR<RiskStatus>("risk-status", () => fetcher(config.getRiskStatus), {
    refreshInterval: 10000,
  });
}

/** One-shot — loaded once, rarely changes. */
export function useRiskLimits() {
  return useSWR<RiskLimits>("risk-limits", () => fetcher(config.getRiskLimits));
}

/** One-shot — loaded once, rarely changes. */
export function useProviders() {
  return useSWR<ProviderInfo[]>("providers", () => fetcher(providers.list));
}

export function useMockStatus() {
  return useSWR<MockSessionStatus>(
    "mock-status",
    () => fetcher(mock.getStatus),
    { refreshInterval: 2000 },
  );
}

/** WS-backed: real-time updates via WebSocket, polling as fallback. */
export function useEngineStatus() {
  return useSWR<EngineStatus>(
    "engine-status",
    () => fetcher(engine.getStatus),
    { refreshInterval: 10000 },
  );
}

export function useEnginePicks() {
  return useSWR<EnginePick[]>(
    "engine-picks",
    () => fetcher(engine.getPicks),
    { refreshInterval: 10000 },
  );
}

/** WS-backed: real-time updates via WebSocket, polling as fallback. */
export function useEngineEvents(limit = 50) {
  return useSWR<EngineEvent[]>(
    `engine-events-${limit}`,
    () => fetcher(() => engine.getEvents(limit)),
    { refreshInterval: 10000 },
  );
}
