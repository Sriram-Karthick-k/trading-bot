/**
 * CreateSessionForm — form for creating a new mock trading session.
 */
"use client";

import { useState } from "react";
import { mock as mockApi } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

interface CreateSessionFormProps {
  onDone: () => void;
}

export function CreateSessionForm({ onDone }: CreateSessionFormProps) {
  const [capital, setCapital] = useState(1000000);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await mockApi.createSession(
      capital,
      startDate || undefined,
      endDate || undefined,
    );
    onDone();
  };

  return (
    <form onSubmit={handleSubmit}>
      <Card className="grid grid-cols-3 gap-4">
        <Input
          label="Initial Capital (₹)"
          type="number"
          value={capital}
          onChange={(e) => setCapital(Number(e.target.value))}
        />
        <Input
          label="Start Date"
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
        />
        <Input
          label="End Date"
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
        />
        <div className="col-span-3 flex gap-3">
          <Button type="submit">Create Session</Button>
          <Button type="button" variant="outline" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </Card>
    </form>
  );
}
