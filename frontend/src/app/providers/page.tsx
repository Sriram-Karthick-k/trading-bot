"use client";

import { useEffect, useState, useCallback } from "react";
import { useProviders } from "@/hooks/useData";
import { providers as providersApi, auth } from "@/lib/api";
import { cn } from "@/lib/utils";

type HealthResult = {
  healthy: boolean;
  latency_ms: number;
  message: string;
};

type AuthSession = {
  authenticated: boolean;
  latency_ms: number | null;
};

export default function ProvidersPage() {
  const { data, isLoading, mutate } = useProviders();
  const [healthMap, setHealthMap] = useState<Record<string, HealthResult>>({});
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);

  // Fetch session status whenever providers change
  const refreshSession = useCallback(async () => {
    try {
      const s = await auth.getSession();
      setSession(s);
    } catch {
      setSession(null);
    }
  }, []);

  // Fetch login URL for the active provider
  const refreshLoginUrl = useCallback(async () => {
    try {
      const resp = await auth.getLoginUrl();
      setLoginUrl(resp.login_url);
    } catch {
      setLoginUrl(null);
    }
  }, []);

  useEffect(() => {
    if (data?.some((p) => p.is_active)) {
      refreshSession();
      refreshLoginUrl();
    }
  }, [data, refreshSession, refreshLoginUrl]);

  // Check health for a provider
  const checkHealth = async (name: string) => {
    try {
      const h = await providersApi.health(name);
      setHealthMap((prev) => ({
        ...prev,
        [name]: { healthy: h.healthy, latency_ms: h.latency_ms, message: h.message },
      }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Health check failed";
      setHealthMap((prev) => ({
        ...prev,
        [name]: { healthy: false, latency_ms: 0, message: msg },
      }));
    }
  };

  // Activate a provider
  const handleActivate = async (name: string) => {
    setActivating(name);
    try {
      await providersApi.activate(name);
      await mutate();
      // After activation, refresh session and login URL
      await refreshSession();
      await refreshLoginUrl();
    } finally {
      setActivating(null);
    }
  };

  // Deactivate the active provider
  const handleDeactivate = async () => {
    await providersApi.deactivate();
    setSession(null);
    setLoginUrl(null);
    setHealthMap({});
    await mutate();
  };

  const activeProvider = data?.find((p) => p.is_active);
  const needsLogin =
    activeProvider &&
    activeProvider.name !== "mock" &&
    (!session?.authenticated);

  return (
    <div className="p-8 space-y-6 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Providers</h2>
          <p className="text-[var(--muted)] text-sm mt-1">
            Manage broker connections &amp; authentication
          </p>
        </div>
        <button
          className="btn-outline"
          onClick={async () => {
            await providersApi.discover();
            mutate();
          }}
        >
          Discover Providers
        </button>
      </div>

      {/* ── Auth Banner ── */}
      {needsLogin && loginUrl && (
        <div className="rounded-xl border-2 border-amber-500/30 bg-amber-500/5 p-5">
          <div className="flex items-start gap-4">
            <span className="text-2xl mt-0.5">🔐</span>
            <div className="flex-1 space-y-3">
              <div>
                <h3 className="font-semibold text-amber-300">
                  Login Required — {activeProvider.display_name}
                </h3>
                <p className="text-sm text-[var(--muted)] mt-1">
                  Provider is activated but not authenticated. Complete the OAuth login
                  to enable trading, market data, and portfolio access.
                </p>
              </div>
              <div className="flex items-center gap-3">
                <a
                  href={loginUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg bg-amber-500 px-4 py-2 text-sm
                    font-semibold text-black hover:bg-amber-400 transition-colors"
                >
                  <span>↗</span> Login with {activeProvider.display_name}
                </a>
                <button
                  className="btn-outline text-xs"
                  onClick={async () => {
                    await refreshSession();
                    if (activeProvider) await checkHealth(activeProvider.name);
                  }}
                >
                  ↻ Check Status
                </button>
              </div>
              <p className="text-xs text-[var(--muted)] font-mono break-all">
                {loginUrl}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Authenticated Banner ── */}
      {activeProvider && session?.authenticated && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
            <div>
              <span className="text-sm font-medium text-emerald-300">
                Connected — {activeProvider.display_name}
              </span>
              {session.latency_ms != null && (
                <span className="text-xs text-[var(--muted)] ml-2">
                  {session.latency_ms.toFixed(0)}ms latency
                </span>
              )}
            </div>
          </div>
          <button className="btn-outline text-xs" onClick={refreshSession}>
            ↻ Refresh
          </button>
        </div>
      )}

      {isLoading && <p className="text-[var(--muted)]">Loading...</p>}

      {/* ── Provider Cards ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {data?.map((p) => {
          const health = healthMap[p.name];
          return (
            <div
              key={p.name}
              className={cn(
                "card border-2 transition-all duration-200",
                p.is_active
                  ? "border-brand-500/50 ring-1 ring-brand-500/20"
                  : "border-[var(--card-border)] hover:border-[var(--card-border)]/80",
              )}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="font-semibold">{p.display_name}</h3>
                  <p className="text-xs text-[var(--muted)] font-mono">{p.name}</p>
                </div>
                <div className="flex items-center gap-2">
                  {p.is_active && (
                    <span className="badge-success">ACTIVE</span>
                  )}
                  {health && (
                    <span
                      className={cn(
                        "w-2.5 h-2.5 rounded-full",
                        health.healthy ? "bg-emerald-400" : "bg-red-400",
                      )}
                      title={health.message}
                    />
                  )}
                </div>
              </div>

              {/* Info */}
              <div className="space-y-2 text-xs text-[var(--muted)] mb-4">
                <p>
                  <span className="text-[var(--foreground)]/60">Exchanges:</span>{" "}
                  {p.supported_exchanges.join(", ")}
                </p>
                {health && (
                  <p
                    className={cn(
                      "text-xs",
                      health.healthy ? "text-emerald-400" : "text-red-400",
                    )}
                  >
                    {health.healthy
                      ? `✓ Healthy (${health.latency_ms.toFixed(1)}ms)`
                      : `✗ ${health.message}`}
                  </p>
                )}
              </div>

              {/* Actions */}
              <div className="flex flex-wrap gap-2">
                {!p.is_active && (
                  <button
                    className="btn-primary text-xs"
                    disabled={activating === p.name}
                    onClick={() => handleActivate(p.name)}
                  >
                    {activating === p.name ? "Activating..." : "Activate"}
                  </button>
                )}
                {p.is_active && (
                  <button
                    className="bg-red-600 hover:bg-red-700 text-white text-xs px-3 py-1.5 rounded-md transition-colors"
                    onClick={handleDeactivate}
                  >
                    Deactivate
                  </button>
                )}
                <button
                  className="btn-outline text-xs"
                  onClick={() => checkHealth(p.name)}
                >
                  Health Check
                </button>
                {p.is_active && p.name !== "mock" && loginUrl && (
                  <a
                    href={loginUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-outline text-xs inline-flex items-center gap-1"
                  >
                    <span>↗</span> Login
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {data?.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-[var(--muted)]">No providers found</p>
          <p className="text-xs text-[var(--muted)] mt-1">
            Click &quot;Discover Providers&quot; to scan for available brokers
          </p>
        </div>
      )}

      {/* ── Auth Flow Help ── */}
      <div className="card bg-[#0c0c0c]">
        <h3 className="text-sm font-semibold mb-3 text-[var(--muted)]">
          How Authentication Works
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs text-[var(--muted)]">
          <Step
            n={1}
            title="Activate Provider"
            desc="Select your broker and click Activate"
          />
          <Step
            n={2}
            title="Login"
            desc="Click the login button to open the broker's OAuth page"
          />
          <Step
            n={3}
            title="Authorize"
            desc="Login with your broker credentials and authorize access"
          />
          <Step
            n={4}
            title="Connected"
            desc="You're redirected back — trading & market data are now live"
          />
        </div>
      </div>
    </div>
  );
}

function Step({ n, title, desc }: { n: number; title: string; desc: string }) {
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-brand-500/10 text-brand-400 flex items-center justify-center text-xs font-bold">
        {n}
      </div>
      <div>
        <p className="font-medium text-[var(--foreground)]">{title}</p>
        <p className="mt-0.5">{desc}</p>
      </div>
    </div>
  );
}
