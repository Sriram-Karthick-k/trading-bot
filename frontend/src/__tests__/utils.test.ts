/**
 * Tests for utility functions.
 */
import { cn, formatCurrency, formatPnl, formatNumber, formatPercent } from "@/lib/utils";

describe("cn()", () => {
  it("merges class names", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("handles conditional classes", () => {
    expect(cn("base", false && "hidden", "visible")).toBe("base visible");
  });

  it("deduplicates tailwind classes", () => {
    expect(cn("p-4", "p-8")).toBe("p-8");
  });
});

describe("formatCurrency()", () => {
  it("formats positive values in INR", () => {
    const result = formatCurrency(1000);
    expect(result).toContain("1,000");
    expect(result).toContain("₹");
  });

  it("formats negative values", () => {
    const result = formatCurrency(-500);
    expect(result).toContain("500");
  });

  it("includes decimals", () => {
    const result = formatCurrency(99.5);
    expect(result).toContain("99.50");
  });

  it("handles zero", () => {
    const result = formatCurrency(0);
    expect(result).toContain("0.00");
  });
});

describe("formatPnl()", () => {
  it("adds + prefix for positive values", () => {
    expect(formatPnl(100)).toMatch(/^\+/);
  });

  it("adds - prefix for negative values", () => {
    expect(formatPnl(-100)).toMatch(/-/);
  });

  it("formats zero with + prefix", () => {
    expect(formatPnl(0)).toMatch(/^\+/);
  });
});

describe("formatNumber()", () => {
  it("formats with default 2 decimals", () => {
    expect(formatNumber(1234.567)).toContain("1,234.57");
  });

  it("respects custom decimals", () => {
    expect(formatNumber(100, 0)).toBe("100");
  });
});

describe("formatPercent()", () => {
  it("adds + for positive percent", () => {
    expect(formatPercent(5.5)).toBe("+5.50%");
  });

  it("shows negative percent", () => {
    expect(formatPercent(-3.2)).toBe("-3.20%");
  });

  it("formats zero", () => {
    expect(formatPercent(0)).toBe("+0.00%");
  });
});
