"use client";

import { useState, useEffect } from "react";
import { useStrategies } from "@/hooks/useData";
import { strategies as strategiesApi } from "@/lib/api";
import { cn, formatPnl } from "@/lib/utils";
import type { StrategyType, ParamSchema } from "@/types";

export default function StrategiesPage() {
  const { data, isLoading, mutate } = useStrategies();
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Strategies</h2>
          <p className="text-[var(--muted)] text-sm mt-1">Configure and monitor trading strategies</p>
        </div>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>
          + New Strategy
        </button>
      </div>

      {showCreate && (
        <CreateStrategyForm
          onDone={() => { setShowCreate(false); mutate(); }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {isLoading && <p className="text-[var(--muted)]">Loading strategies...</p>}

      {!showCreate && data?.length === 0 && (
        <div className="card text-center py-12">
          <p className="text-[var(--muted)]">No strategies configured yet</p>
          <p className="text-xs text-[var(--muted)] mt-2">
            Click &quot;+ New Strategy&quot; to create your first trading strategy
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {data?.map((s) => (
          <div key={s.strategy_id} className="card space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold">{s.name}</h3>
                <p className="text-xs text-[var(--muted)] font-mono">{s.strategy_id}</p>
              </div>
              <StateBadge state={s.state} />
            </div>

            <div className="grid grid-cols-4 gap-4 text-center">
              <div>
                <p className="text-xs text-[var(--muted)]">Signals</p>
                <p className="font-mono font-bold">{s.metrics.total_signals}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--muted)]">Trades</p>
                <p className="font-mono font-bold">{s.metrics.total_trades}</p>
              </div>
              <div>
                <p className="text-xs text-[var(--muted)]">Win Rate</p>
                <p className="font-mono font-bold">
                  {s.metrics.total_trades > 0
                    ? `${((s.metrics.winning_trades / s.metrics.total_trades) * 100).toFixed(0)}%`
                    : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs text-[var(--muted)]">P&L</p>
                <p className={cn("font-mono font-bold", s.metrics.total_pnl >= 0 ? "pnl-positive" : "pnl-negative")}>
                  {formatPnl(s.metrics.total_pnl)}
                </p>
              </div>
            </div>

            <div className="flex gap-2">
              {s.state === "idle" || s.state === "stopped" ? (
                <button
                  className="btn-primary text-xs"
                  onClick={async () => { await strategiesApi.start(s.strategy_id); mutate(); }}
                >
                  Start
                </button>
              ) : s.state === "running" ? (
                <>
                  <button
                    className="btn-outline text-xs"
                    onClick={async () => { await strategiesApi.pause(s.strategy_id); mutate(); }}
                  >
                    Pause
                  </button>
                  <button
                    className="btn-danger text-xs"
                    onClick={async () => { await strategiesApi.stop(s.strategy_id); mutate(); }}
                  >
                    Stop
                  </button>
                </>
              ) : s.state === "paused" ? (
                <>
                  <button
                    className="btn-primary text-xs"
                    onClick={async () => { await strategiesApi.resume(s.strategy_id); mutate(); }}
                  >
                    Resume
                  </button>
                  <button
                    className="btn-danger text-xs"
                    onClick={async () => { await strategiesApi.stop(s.strategy_id); mutate(); }}
                  >
                    Stop
                  </button>
                </>
              ) : null}
              <button
                className="btn-outline text-xs text-red-400 border-red-500/30 hover:bg-red-500/10 ml-auto"
                onClick={async () => {
                  if (confirm(`Delete strategy "${s.strategy_id}"?`)) {
                    await strategiesApi.delete(s.strategy_id);
                    mutate();
                  }
                }}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CreateStrategyForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [types, setTypes] = useState<StrategyType[]>([]);
  const [selectedType, setSelectedType] = useState("");
  const [strategyId, setStrategyId] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    strategiesApi.types().then(setTypes).catch(() => {});
  }, []);

  const selectedSchema = types.find((t) => t.name === selectedType);

  useEffect(() => {
    if (selectedSchema) {
      const defaults: Record<string, unknown> = {};
      for (const p of selectedSchema.params_schema) {
        defaults[p.name] = p.default;
      }
      setParams(defaults);
      setStrategyId(`${selectedType}_${Date.now().toString(36)}`);
    }
  }, [selectedType, selectedSchema]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await strategiesApi.create(selectedType, strategyId, params);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create strategy");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card border-2 border-brand-500/30">
      <h3 className="font-semibold text-lg mb-4">Create New Strategy</h3>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-[var(--muted)] block mb-1">Strategy Type</label>
            <select
              className="input w-full"
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              required
            >
              <option value="">Select a strategy...</option>
              {types.map((t) => (
                <option key={t.name} value={t.name}>{t.name}</option>
              ))}
            </select>
            {selectedSchema && (
              <p className="text-xs text-[var(--muted)] mt-1">{selectedSchema.description}</p>
            )}
          </div>
          <div>
            <label className="text-xs text-[var(--muted)] block mb-1">Strategy ID</label>
            <input
              className="input w-full"
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              placeholder="my_strategy_1"
              required
            />
          </div>
        </div>

        {selectedSchema && (
          <div>
            <h4 className="text-sm font-medium mb-3 text-[var(--muted)]">Parameters</h4>
            <div className="grid grid-cols-2 gap-3">
              {selectedSchema.params_schema.map((p) => (
                <ParamInput
                  key={p.name}
                  schema={p}
                  value={params[p.name]}
                  onChange={(v) => setParams({ ...params, [p.name]: v })}
                />
              ))}
            </div>
          </div>
        )}

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <div className="flex gap-3">
          <button type="submit" className="btn-primary" disabled={submitting || !selectedType}>
            {submitting ? "Creating..." : "Create Strategy"}
          </button>
          <button type="button" className="btn-outline" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </div>
  );
}

function ParamInput({ schema, value, onChange }: { schema: ParamSchema; value: unknown; onChange: (v: unknown) => void }) {
  const inputType = schema.type === "int" || schema.type === "float" ? "number" : "text";
  const step = schema.type === "float" ? "0.01" : "1";

  return (
    <div>
      <label className="text-xs text-[var(--muted)] block mb-1">
        {schema.label || schema.name}
        {schema.required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {schema.type === "enum" && schema.enum_values ? (
        <select
          className="input w-full"
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        >
          {schema.enum_values.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      ) : schema.type === "bool" ? (
        <select
          className="input w-full"
          value={String(value ?? false)}
          onChange={(e) => onChange(e.target.value === "true")}
        >
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : (
        <input
          className="input w-full"
          type={inputType}
          step={step}
          min={schema.min_value ?? undefined}
          max={schema.max_value ?? undefined}
          value={String(value ?? "")}
          onChange={(e) => {
            const v = e.target.value;
            onChange(schema.type === "int" ? parseInt(v) || 0 : schema.type === "float" ? parseFloat(v) || 0 : v);
          }}
        />
      )}
      {schema.description && (
        <p className="text-xs text-[var(--muted)] mt-0.5">{schema.description}</p>
      )}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const styles: Record<string, string> = {
    idle: "badge bg-gray-500/10 text-gray-400",
    running: "badge-success",
    paused: "badge-warning",
    stopped: "badge bg-gray-500/10 text-gray-400",
    error: "badge-danger",
  };
  return <span className={styles[state] || "badge-info"}>{state.toUpperCase()}</span>;
}
