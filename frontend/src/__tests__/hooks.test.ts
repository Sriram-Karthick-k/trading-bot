/**
 * Tests for the useTickStream and useEngineStream hooks.
 */
import { renderHook, act } from "@testing-library/react";
import { useTickStream } from "@/hooks/useTickStream";
import { useEngineStream } from "@/hooks/useEngineStream";

// Mock WebSocket
class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static CONNECTING = 0;
  static CLOSING = 2;
  static instances: MockWebSocket[] = [];
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sentMessages: string[] = [];

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
    // Simulate connection in next tick
    setTimeout(() => this.onopen?.(), 0);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close() {
    this.onclose?.();
  }
}

beforeEach(() => {
  MockWebSocket.instances = [];
  (global as unknown as Record<string, unknown>).WebSocket = MockWebSocket;
});

afterEach(() => {
  delete (global as unknown as Record<string, unknown>).WebSocket;
});

describe("useTickStream", () => {
  it("connects to websocket", async () => {
    renderHook(() =>
      useTickStream({ clientId: "test", tokens: [256265] }),
    );

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/ticks/test");
  });

  it("does not connect when disabled", () => {
    renderHook(() =>
      useTickStream({ clientId: "test", tokens: [256265], enabled: false }),
    );

    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("sends subscribe message on connect", async () => {
    renderHook(() =>
      useTickStream({ clientId: "test", tokens: [256265] }),
    );

    // Trigger onopen
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = MockWebSocket.instances[0];
    expect(ws.sentMessages).toHaveLength(1);
    const msg = JSON.parse(ws.sentMessages[0]);
    expect(msg.action).toBe("subscribe");
    expect(msg.tokens).toEqual([256265]);
  });

  it("calls onTick callback with tick data", async () => {
    const onTick = jest.fn();
    renderHook(() =>
      useTickStream({ clientId: "test", tokens: [256265], onTick }),
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ instrument_token: 256265, last_price: 22000 }),
      });
    });

    expect(onTick).toHaveBeenCalledWith({
      instrument_token: 256265,
      last_price: 22000,
    });
  });

  it("exposes subscribe/unsubscribe methods", async () => {
    const { result } = renderHook(() =>
      useTickStream({ clientId: "test", tokens: [] }),
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    act(() => {
      result.current.subscribe([12345]);
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    const msg = JSON.parse(ws.sentMessages[ws.sentMessages.length - 1]);
    expect(msg.action).toBe("subscribe");
    expect(msg.tokens).toEqual([12345]);
  });
});

describe("useEngineStream", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("connects to websocket and sends subscribe_engine", async () => {
    const { result } = renderHook(() => useEngineStream());

    // Trigger onopen
    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    // Should have created at least one WebSocket instance
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(1);

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws.url).toContain("/ws/ticks/engine_");

    // Should send subscribe_engine on connect
    const subscribeMsg = ws.sentMessages.find((m) => {
      const parsed = JSON.parse(m);
      return parsed.action === "subscribe_engine";
    });
    expect(subscribeMsg).toBeDefined();
  });

  it("does not connect when disabled", () => {
    const initialCount = MockWebSocket.instances.length;
    renderHook(() => useEngineStream({ enabled: false }));

    expect(MockWebSocket.instances.length).toBe(initialCount);
  });

  it("sets connected=true on engine_subscribed message", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "engine_subscribed" }),
      });
    });

    expect(result.current.connected).toBe(true);
  });

  it("receives engine events", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    // First set connected
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "engine_subscribed" }),
      });
    });

    // Send an engine event
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({
          type: "engine_event",
          event: {
            timestamp: "2025-01-15T10:00:00",
            type: "info",
            message: "Engine started",
            data: {},
          },
        }),
      });
    });

    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0].message).toBe("Engine started");
    expect(result.current.events[0].type).toBe("info");
  });

  it("receives engine status updates", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({
          type: "engine_status",
          status: {
            state: "running",
            picks_count: 5,
            strategies_count: 5,
            ticker_connected: true,
            started_at: "2025-01-15T09:15:00",
            stopped_at: null,
            metrics: {
              total_signals: 0,
              total_orders: 0,
              total_fills: 0,
              session_pnl: 0,
            },
            strategies: {},
            recent_events: [],
          },
        }),
      });
    });

    expect(result.current.status).not.toBeNull();
    expect(result.current.status?.state).toBe("running");
    expect(result.current.status?.picks_count).toBe(5);
  });

  it("caps events at maxEvents limit", async () => {
    const { result } = renderHook(() =>
      useEngineStream({ maxEvents: 3 }),
    );

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    // Send 5 events — should keep only last 3
    for (let i = 0; i < 5; i++) {
      act(() => {
        ws.onmessage?.({
          data: JSON.stringify({
            type: "engine_event",
            event: {
              timestamp: `2025-01-15T10:0${i}:00`,
              type: "info",
              message: `Event ${i}`,
              data: {},
            },
          }),
        });
      });
    }

    expect(result.current.events).toHaveLength(3);
    expect(result.current.events[0].message).toBe("Event 2");
    expect(result.current.events[2].message).toBe("Event 4");
  });

  it("clearEvents resets event buffer", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({
          type: "engine_event",
          event: {
            timestamp: "2025-01-15T10:00:00",
            type: "info",
            message: "test",
            data: {},
          },
        }),
      });
    });

    expect(result.current.events).toHaveLength(1);

    act(() => {
      result.current.clearEvents();
    });

    expect(result.current.events).toHaveLength(0);
  });

  it("ignores tick messages", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({
          type: "tick",
          instrument_token: 256265,
          last_price: 22000,
        }),
      });
    });

    // Should not affect events or status
    expect(result.current.events).toHaveLength(0);
    expect(result.current.status).toBeNull();
  });

  it("handles malformed messages gracefully", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    // Send malformed JSON — should not crash
    act(() => {
      ws.onmessage?.({ data: "not json" });
    });

    expect(result.current.events).toHaveLength(0);
  });

  it("sets connected=false on close", async () => {
    const { result } = renderHook(() => useEngineStream());

    await act(async () => {
      jest.advanceTimersByTime(10);
      await Promise.resolve();
    });

    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

    // Simulate connected
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "engine_subscribed" }),
      });
    });
    expect(result.current.connected).toBe(true);

    // Simulate close
    act(() => {
      ws.onclose?.();
    });
    expect(result.current.connected).toBe(false);
  });
});
