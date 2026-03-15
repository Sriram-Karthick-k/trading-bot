/**
 * Tests for the useTickStream hook.
 */
import { renderHook, act } from "@testing-library/react";
import { useTickStream } from "@/hooks/useTickStream";

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
