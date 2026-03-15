/**
 * SWR-based data fetching hooks.
 */

import useSWR from "swr";
import { orders, portfolio, strategies, config, providers, mock } from "@/lib/api";
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
} from "@/types";

const fetcher = <T>(fn: () => Promise<T>) => fn();

export function useOrders() {
  return useSWR<Order[]>("orders", () => fetcher(orders.getAll), {
    refreshInterval: 3000,
  });
}

export function usePositions() {
  return useSWR<{ net: Position[]; day: Position[] }>(
    "positions",
    () => fetcher(portfolio.getPositions),
    { refreshInterval: 3000 },
  );
}

export function useHoldings() {
  return useSWR<Holding[]>("holdings", () => fetcher(portfolio.getHoldings), {
    refreshInterval: 10000,
  });
}

export function useMargins() {
  return useSWR<Margins>("margins", () => fetcher(portfolio.getMargins), {
    refreshInterval: 5000,
  });
}

export function useStrategies() {
  return useSWR<StrategySnapshot[]>(
    "strategies",
    () => fetcher(strategies.list),
    { refreshInterval: 2000 },
  );
}

export function useRiskStatus() {
  return useSWR<RiskStatus>("risk-status", () => fetcher(config.getRiskStatus), {
    refreshInterval: 2000,
  });
}

export function useRiskLimits() {
  return useSWR<RiskLimits>("risk-limits", () => fetcher(config.getRiskLimits));
}

export function useProviders() {
  return useSWR<ProviderInfo[]>("providers", () => fetcher(providers.list));
}

export function useMockStatus() {
  return useSWR<MockSessionStatus>(
    "mock-status",
    () => fetcher(mock.getStatus),
    { refreshInterval: 1000 },
  );
}
