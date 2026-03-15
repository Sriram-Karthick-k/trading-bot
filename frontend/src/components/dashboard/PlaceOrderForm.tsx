/**
 * PlaceOrderForm — form for placing new orders.
 */
"use client";

import { useState } from "react";
import { orders as ordersApi } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { Card } from "@/components/ui/Card";

interface PlaceOrderFormProps {
  onDone: () => void;
}

export function PlaceOrderForm({ onDone }: PlaceOrderFormProps) {
  const [form, setForm] = useState({
    exchange: "NSE",
    trading_symbol: "",
    transaction_type: "BUY",
    order_type: "MARKET",
    quantity: 1,
    product: "CNC",
    price: undefined as number | undefined,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await ordersApi.place(form);
    onDone();
  };

  return (
    <form onSubmit={handleSubmit}>
      <Card className="grid grid-cols-4 gap-4">
        <Input
          label="Symbol"
          value={form.trading_symbol}
          onChange={(e) => setForm({ ...form, trading_symbol: e.target.value })}
          placeholder="RELIANCE"
          required
        />
        <Select
          label="Side"
          value={form.transaction_type}
          onChange={(e) => setForm({ ...form, transaction_type: e.target.value })}
          options={[
            { value: "BUY", label: "BUY" },
            { value: "SELL", label: "SELL" },
          ]}
        />
        <Input
          label="Quantity"
          type="number"
          min={1}
          value={form.quantity}
          onChange={(e) => setForm({ ...form, quantity: parseInt(e.target.value) || 1 })}
        />
        <Select
          label="Type"
          value={form.order_type}
          onChange={(e) => setForm({ ...form, order_type: e.target.value })}
          options={[
            { value: "MARKET", label: "MARKET" },
            { value: "LIMIT", label: "LIMIT" },
            { value: "SL", label: "SL" },
            { value: "SL-M", label: "SL-M" },
          ]}
        />
        {form.order_type === "LIMIT" && (
          <Input
            label="Price"
            type="number"
            step="0.05"
            value={form.price ?? ""}
            onChange={(e) =>
              setForm({ ...form, price: parseFloat(e.target.value) || undefined })
            }
          />
        )}
        <div className="col-span-4 flex gap-3">
          <Button type="submit">Place Order</Button>
          <Button type="button" variant="outline" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </Card>
    </form>
  );
}
