"use client";

import { useState, useEffect, useRef } from "react";
import { useOrders } from "@/hooks/useData";
import { orders as ordersApi, market as marketApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Instrument } from "@/types";

export default function OrdersPage() {
  const { data: orderList, isLoading, mutate } = useOrders();
  const [placing, setPlacing] = useState(false);

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Orders</h2>
          <p className="text-[var(--muted)] text-sm mt-1">Manage and track all orders</p>
        </div>
        <button className="btn-primary" onClick={() => setPlacing(!placing)}>
          + Place Order
        </button>
      </div>

      {placing && <PlaceOrderForm onDone={() => { setPlacing(false); mutate(); }} />}

      <div className="card overflow-hidden p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--card-border)] bg-white/[0.02]">
              <th className="text-left p-4 text-xs text-[var(--muted)] font-medium uppercase">Symbol</th>
              <th className="text-left p-4 text-xs text-[var(--muted)] font-medium uppercase">Type</th>
              <th className="text-right p-4 text-xs text-[var(--muted)] font-medium uppercase">Qty</th>
              <th className="text-right p-4 text-xs text-[var(--muted)] font-medium uppercase">Price</th>
              <th className="text-right p-4 text-xs text-[var(--muted)] font-medium uppercase">Avg Price</th>
              <th className="text-center p-4 text-xs text-[var(--muted)] font-medium uppercase">Status</th>
              <th className="p-4 text-xs text-[var(--muted)] font-medium uppercase">Time</th>
              <th className="p-4"></th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={8} className="p-8 text-center text-[var(--muted)]">Loading...</td></tr>
            )}
            {orderList?.length === 0 && (
              <tr><td colSpan={8} className="p-8 text-center text-[var(--muted)]">No orders</td></tr>
            )}
            {orderList?.map((o) => (
              <tr key={o.order_id} className="border-b border-[var(--card-border)] hover:bg-white/[0.02]">
                <td className="p-4">
                  <span className="font-medium">{o.trading_symbol}</span>
                  <span className="text-xs text-[var(--muted)] ml-1">{o.exchange}</span>
                </td>
                <td className="p-4">
                  <span className={cn(
                    "text-xs font-medium px-2 py-0.5 rounded",
                    o.transaction_type === "BUY" ? "bg-emerald-500/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                  )}>
                    {o.transaction_type}
                  </span>
                  <span className="text-xs text-[var(--muted)] ml-2">{o.order_type}</span>
                </td>
                <td className="p-4 text-right font-mono">{o.filled_quantity}/{o.quantity}</td>
                <td className="p-4 text-right font-mono">{o.price?.toFixed(2) ?? "MKT"}</td>
                <td className="p-4 text-right font-mono">{o.average_price.toFixed(2)}</td>
                <td className="p-4 text-center">
                  <StatusBadge status={o.status} />
                </td>
                <td className="p-4 text-xs text-[var(--muted)]">
                  {o.placed_at ? new Date(o.placed_at).toLocaleTimeString() : "—"}
                </td>
                <td className="p-4">
                  {(o.status === "PENDING" || o.status === "OPEN") && (
                    <button
                      className="text-xs text-red-400 hover:text-red-300"
                      onClick={async () => {
                        await ordersApi.cancel("regular", o.order_id);
                        mutate();
                      }}
                    >
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PlaceOrderForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({
    exchange: "NSE",
    trading_symbol: "",
    transaction_type: "BUY",
    order_type: "MARKET",
    quantity: 1,
    product: "CNC",
    price: undefined as number | undefined,
  });

  // Instrument search state
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loadingInstruments, setLoadingInstruments] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

  // Load instruments when exchange changes
  useEffect(() => {
    setLoadingInstruments(true);
    marketApi
      .getInstruments(form.exchange)
      .then(setInstruments)
      .catch(() => setInstruments([]))
      .finally(() => setLoadingInstruments(false));
  }, [form.exchange]);

  // Close suggestions on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = searchQuery.length >= 1
    ? instruments.filter((i) =>
        i.trading_symbol.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (i.name && i.name.toLowerCase().includes(searchQuery.toLowerCase()))
      ).slice(0, 20)
    : [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await ordersApi.place(form);
    onDone();
  };

  return (
    <form onSubmit={handleSubmit} className="card grid grid-cols-4 gap-4">
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">Exchange</label>
        <select
          className="input w-full"
          value={form.exchange}
          onChange={(e) => {
            setForm({ ...form, exchange: e.target.value, trading_symbol: "" });
            setSearchQuery("");
          }}
        >
          <option value="NSE">NSE</option>
          <option value="BSE">BSE</option>
          <option value="NFO">NFO</option>
          <option value="CDS">CDS</option>
          <option value="MCX">MCX</option>
        </select>
      </div>
      <div ref={searchRef} className="relative">
        <label className="text-xs text-[var(--muted)] block mb-1">
          Symbol {loadingInstruments && <span className="text-[var(--muted)]">(loading...)</span>}
        </label>
        <input
          className="input w-full"
          value={searchQuery || form.trading_symbol}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setForm({ ...form, trading_symbol: e.target.value.toUpperCase() });
            setShowSuggestions(true);
          }}
          onFocus={() => searchQuery.length >= 1 && setShowSuggestions(true)}
          placeholder="Search RELIANCE, TCS..."
          required
        />
        {showSuggestions && filtered.length > 0 && (
          <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-[var(--card)] border border-[var(--card-border)] rounded-lg shadow-xl max-h-48 overflow-y-auto">
            {filtered.map((inst) => (
              <button
                type="button"
                key={`${inst.exchange}-${inst.trading_symbol}`}
                className="w-full text-left px-3 py-2 hover:bg-white/5 text-sm flex justify-between items-center"
                onClick={() => {
                  setForm({ ...form, trading_symbol: inst.trading_symbol });
                  setSearchQuery(inst.trading_symbol);
                  setShowSuggestions(false);
                }}
              >
                <span className="font-medium">{inst.trading_symbol}</span>
                <span className="text-xs text-[var(--muted)]">{inst.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">Side</label>
        <select
          className="input w-full"
          value={form.transaction_type}
          onChange={(e) => setForm({ ...form, transaction_type: e.target.value })}
        >
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
      </div>
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">Quantity</label>
        <input
          className="input w-full"
          type="number"
          min={1}
          value={form.quantity}
          onChange={(e) => setForm({ ...form, quantity: parseInt(e.target.value) || 1 })}
        />
      </div>
      <div>
        <label className="text-xs text-[var(--muted)] block mb-1">Type</label>
        <select
          className="input w-full"
          value={form.order_type}
          onChange={(e) => setForm({ ...form, order_type: e.target.value })}
        >
          <option value="MARKET">MARKET</option>
          <option value="LIMIT">LIMIT</option>
          <option value="SL">SL</option>
          <option value="SL-M">SL-M</option>
        </select>
      </div>
      {form.order_type === "LIMIT" && (
        <div>
          <label className="text-xs text-[var(--muted)] block mb-1">Price</label>
          <input
            className="input w-full"
            type="number"
            step="0.05"
            value={form.price ?? ""}
            onChange={(e) => setForm({ ...form, price: parseFloat(e.target.value) || undefined })}
          />
        </div>
      )}
      <div className="col-span-4 flex gap-3">
        <button type="submit" className="btn-primary">Place Order</button>
        <button type="button" className="btn-outline" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    COMPLETE: "badge-success",
    REJECTED: "badge-danger",
    CANCELLED: "badge-warning",
    PENDING: "badge-info",
    OPEN: "badge-info",
  };
  return <span className={styles[status] || "badge-info"}>{status}</span>;
}
