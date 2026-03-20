"use client";

/**
 * Global SWR configuration provider.
 *
 * Sets sensible defaults to reduce unnecessary re-fetches:
 * - revalidateOnFocus: false (no burst on tab switch)
 * - revalidateOnReconnect: false (no burst on network reconnect)
 * - dedupingInterval: 5000ms (dedup identical requests within 5s)
 * - errorRetryCount: 3
 */

import { SWRConfig } from "swr";

export function SWRProvider({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: false,
        revalidateOnReconnect: false,
        dedupingInterval: 5000,
        errorRetryCount: 3,
      }}
    >
      {children}
    </SWRConfig>
  );
}
