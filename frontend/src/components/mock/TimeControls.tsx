/**
 * TimeControls — mock session time manipulation panel.
 */
"use client";

import { useState } from "react";
import { mock as mockApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { MockSessionStatus } from "@/types";
import { Card, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/ProgressBar";

interface TimeControlsProps {
  status: MockSessionStatus;
  onAction: () => void;
}

export function TimeControls({ status, onAction }: TimeControlsProps) {
  const [dateInput, setDateInput] = useState("");

  return (
    <Card>
      <CardTitle className="mb-4">Time Controls</CardTitle>

      <ProgressBar
        value={status.progress}
        className="mb-4"
        barClassName="bg-brand-500"
        label={`${(status.progress * 100).toFixed(1)}% complete`}
      />

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={async () => { await mockApi.marketOpen(); onAction(); }}
        >
          → Market Open
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={async () => { await mockApi.marketClose(); onAction(); }}
        >
          → Market Close
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={async () => { await mockApi.nextDay(); onAction(); }}
        >
          → Next Day
        </Button>

        <div className="border-l border-[var(--card-border)] mx-2" />

        {status.paused ? (
          <Button
            size="sm"
            onClick={async () => { await mockApi.resume(); onAction(); }}
          >
            ▶ Resume
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            onClick={async () => { await mockApi.pause(); onAction(); }}
          >
            ⏸ Pause
          </Button>
        )}

        {[1, 5, 10, 50, 100].map((speed) => (
          <Button
            key={speed}
            variant="outline"
            size="sm"
            className={cn(
              status.speed === speed && "bg-brand-600 border-brand-600",
            )}
            onClick={async () => { await mockApi.setSpeed(speed); onAction(); }}
          >
            {speed}x
          </Button>
        ))}

        <div className="border-l border-[var(--card-border)] mx-2" />

        <input
          type="date"
          className="input text-xs"
          value={dateInput}
          onChange={(e) => setDateInput(e.target.value)}
        />
        <Button
          variant="outline"
          size="sm"
          disabled={!dateInput}
          onClick={async () => { await mockApi.setDate(dateInput); onAction(); }}
        >
          Jump to Date
        </Button>

        <div className="border-l border-[var(--card-border)] mx-2" />

        <Button
          variant="danger"
          size="sm"
          onClick={async () => { await mockApi.reset(); onAction(); }}
        >
          Reset Session
        </Button>
      </div>
    </Card>
  );
}
