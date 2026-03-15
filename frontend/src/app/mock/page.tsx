"use client";

import { useState, useEffect } from "react";
import { useMockStatus } from "@/hooks/useData";
import { mock as mockApi } from "@/lib/api";
import { cn, formatCurrency, formatPnl } from "@/lib/utils";

export default function MockPage() {
  const { data: status, mutate } = useMockStatus();
  const [creating, setCreating] = useState(false);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Paper Trading</h2>
          <p className="text-[var(--muted)] text-sm mt-1">
            Practice trading with virtual capital — no real money at risk
          </p>
        </div>
        <button className="btn-primary" onClick={() => setCreating(!creating)}>
          + New Session
        </button>
      </div>

      {creating && <CreateSessionForm onDone={() => { setCreating(false); mutate(); }} />}

      {status && (
        <>
          <SessionOverview status={status} />
          <MockInstruments onRefresh={mutate} />
          <TimeControls status={status} onAction={mutate} />
          <MockPositions />
        </>
      )}

      {!status && !creating && (
        <div className="card text-center py-16">
          <p className="text-4xl mb-4">📊</p>
          <h3 className="font-semibold text-lg">No active paper trading session</h3>
          <p className="text-sm text-[var(--muted)] mt-2 max-w-md mx-auto">
            Paper trading lets you test strategies with virtual money.
            Create a session, load sample market data, then place orders
            or run automated strategies.
          </p>
          <div className="mt-6">
            <button className="btn-primary" onClick={() => setCreating(true)}>
              Start Paper Trading
            </button>
          </div>
          <div className="mt-8 text-left max-w-lg mx-auto space-y-3">
            <h4 className="text-sm font-medium text-[var(--muted)]">How it works:</h4>
            <div className="text-xs text-[var(--muted)] space-y-2">
              <p>1. <strong>Create a session</strong> — Set your virtual capital (default ₹10L)</p>
              <p>2. <strong>Load sample data</strong> — Get prices for 20 popular NSE stocks</p>
              <p>3. <strong>Place orders</strong> — Go to Orders page to buy/sell stocks</p>
              <p>4. <strong>Run strategies</strong> — Create an SMA or RSI strategy to auto-trade</p>
              <p>5. <strong>Track P&L</strong> — Monitor positions and profit/loss in real-time</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CreateSessionForm({ onDone }: { onDone: () => void }) {
  const [capital, setCapital] = useState(1000000);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await mockApi.createSession(capital, startDate || undefined, endDate || undefined);
      // Auto-load sample data when creating session
      await mockApi.loadSampleData();
      onDone();
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="card grid grid-cols-3 gap-4">
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">Initial Capital (₹)</label>
        <input
          className="input w-full"
          type="number"
          value={capital}
          onChange={(e) => setCapital(Number(e.target.value))}
        />
      </div>
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">Start Date (optional)</label>
        <input
          className="input w-full"
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
      </div>
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">End Date (optional)</label>
        <input
          className="input w-full"
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
        />
      </div>
      <div className="col-span-3 flex gap-3">
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? "Creating..." : "Create Session & Load Sample Data"}
        </button>
        <button type="button" className="btn-outline" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

function SessionOverview({ status }: { status: import("@/types").MockSessionStatus }) {
  return (
    <div className="grid grid-cols-5 gap-4">
      <div className="card">
        <p className="text-xs text-[var(--muted)] uppercase">Capital</p>
        <p className="text-lg font-bold font-mono mt-1">{formatCurrency(status.virtual_capital)}</p>
      </div>
      <div className="card">
        <p className="text-xs text-[var(--muted)] uppercase">Total P&L</p>
        <p className={cn("text-lg font-bold font-mono mt-1", status.total_pnl >= 0 ? "pnl-positive" : "pnl-negative")}>
          {formatPnl(status.total_pnl)}
        </p>
      </div>
      <div className="card">
        <p className="text-xs text-[var(--muted)] uppercase">Current Time</p>
        <p className="text-sm font-mono mt-1">
          {new Date(status.current_time).toLocaleString("en-IN")}
        </p>
      </div>
      <div className="card">
        <p className="text-xs text-[var(--muted)] uppercase">Market</p>
        <p className={cn("text-lg font-bold mt-1", status.is_market_open ? "text-emerald-400" : "text-[var(--muted)]")}>
          {status.is_market_open ? "OPEN" : "CLOSED"}
        </p>
      </div>
      <div className="card">
        <p className="text-xs text-[var(--muted)] uppercase">Speed</p>
        <p className="text-lg font-bold font-mono mt-1">{status.speed}x</p>
      </div>
    </div>
  );
}

function MockInstruments({ onRefresh }: { onRefresh: () => void }) {
  const [instruments, setInstruments] = useState<{ symbol: string; token: number; name: string; ltp: number; exchange: string }[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    mockApi.getInstruments().then(setInstruments).catch(() => {});
  }, []);

  const handleLoadData = async () => {
    setLoading(true);
    try {
      await mockApi.loadSampleData();
      const data = await mockApi.getInstruments();
      setInstruments(data);
      onRefresh();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold">Available Instruments ({instruments.length})</h3>
        <button className="btn-outline text-xs" onClick={handleLoadData} disabled={loading}>
          {loading ? "Loading..." : "Reload Sample Data"}
        </button>
      </div>
      {instruments.length === 0 ? (
        <p className="text-[var(--muted)] text-sm">No instruments loaded. Click &quot;Reload Sample Data&quot; to load 20 popular NSE stocks.</p>
      ) : (
        <div className="grid grid-cols-4 gap-2">
          {instruments.map((i) => (
            <div key={i.token} className="flex items-center justify-between py-1.5 px-2 rounded bg-white/[0.02]">
              <div>
                <span className="text-sm font-medium">{i.symbol}</span>
                <span className="text-xs text-[var(--muted)] ml-1">{i.exchange}</span>
              </div>
              <span className="text-sm font-mono text-[var(--muted)]">₹{i.ltp.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TimeControls({
  status,
  onAction,
}: {
  status: import("@/types").MockSessionStatus;
  onAction: () => void;
}) {
  const [dateInput, setDateInput] = useState("");

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Time Controls</h3>

      {/* Progress bar */}
      <div className="mb-4">
        <div className="h-2 rounded-full bg-white/5 overflow-hidden">
          <div
            className="h-full rounded-full bg-brand-500 transition-all"
            style={{ width: `${status.progress * 100}%` }}
          />
        </div>
        <p className="text-xs text-[var(--muted)] mt-1">{(status.progress * 100).toFixed(1)}% complete</p>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          className="btn-outline text-xs"
          onClick={async () => { await mockApi.marketOpen(); onAction(); }}
        >
          → Market Open
        </button>
        <button
          className="btn-outline text-xs"
          onClick={async () => { await mockApi.marketClose(); onAction(); }}
        >
          → Market Close
        </button>
        <button
          className="btn-outline text-xs"
          onClick={async () => { await mockApi.nextDay(); onAction(); }}
        >
          → Next Day
        </button>

        <div className="border-l border-[var(--card-border)] mx-2" />

        {status.paused ? (
          <button
            className="btn-primary text-xs"
            onClick={async () => { await mockApi.resume(); onAction(); }}
          >
            ▶ Resume
          </button>
        ) : (
          <button
            className="btn-outline text-xs"
            onClick={async () => { await mockApi.pause(); onAction(); }}
          >
            ⏸ Pause
          </button>
        )}

        {[1, 5, 10, 50, 100].map((speed) => (
          <button
            key={speed}
            className={cn("btn-outline text-xs", status.speed === speed && "bg-brand-600 border-brand-600")}
            onClick={async () => { await mockApi.setSpeed(speed); onAction(); }}
          >
            {speed}x
          </button>
        ))}

        <div className="border-l border-[var(--card-border)] mx-2" />

        <input
          type="date"
          className="input text-xs"
          value={dateInput}
          onChange={(e) => setDateInput(e.target.value)}
        />
        <button
          className="btn-outline text-xs"
          disabled={!dateInput}
          onClick={async () => { await mockApi.setDate(dateInput); onAction(); }}
        >
          Jump to Date
        </button>

        <div className="border-l border-[var(--card-border)] mx-2" />

        <button
          className="btn-danger text-xs"
          onClick={async () => { await mockApi.reset(); onAction(); }}
        >
          Reset Session
        </button>
      </div>
    </div>
  );
}

function MockPositions() {
  const { data: status } = useMockStatus();

  return (
    <div className="card">
      <h3 className="text-sm font-semibold mb-4">Session Stats</h3>
      <div className="grid grid-cols-3 gap-4">
        <div>
          <p className="text-xs text-[var(--muted)]">Open Orders</p>
          <p className="text-xl font-mono font-bold">{status?.open_orders ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">Open Positions</p>
          <p className="text-xl font-mono font-bold">{status?.positions ?? 0}</p>
        </div>
        <div>
          <p className="text-xs text-[var(--muted)]">Unrealized P&L</p>
          <p className={cn("text-xl font-mono font-bold", (status?.total_pnl ?? 0) >= 0 ? "pnl-positive" : "pnl-negative")}>
            {formatPnl(status?.total_pnl ?? 0)}
          </p>
        </div>
      </div>
    </div>
  );
}
