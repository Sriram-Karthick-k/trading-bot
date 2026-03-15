/**
 * Tests for UI components.
 */
import React from "react";
import { render, screen } from "@testing-library/react";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Input, Select } from "@/components/ui/Input";
import { MetricCard } from "@/components/ui/MetricCard";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState } from "@/components/ui/EmptyState";

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Hello Card</Card>);
    expect(screen.getByText("Hello Card")).toBeInTheDocument();
  });

  it("applies noPadding class", () => {
    const { container } = render(<Card noPadding>Content</Card>);
    expect(container.firstChild).toHaveClass("p-0");
  });

  it("accepts custom className", () => {
    const { container } = render(<Card className="custom-class">Content</Card>);
    expect(container.firstChild).toHaveClass("custom-class");
  });
});

describe("CardHeader + CardTitle", () => {
  it("renders header with title", () => {
    render(
      <CardHeader>
        <CardTitle>Test Title</CardTitle>
      </CardHeader>,
    );
    expect(screen.getByText("Test Title")).toBeInTheDocument();
  });
});

describe("Button", () => {
  it("renders with text", () => {
    render(<Button>Click Me</Button>);
    expect(screen.getByRole("button", { name: "Click Me" })).toBeInTheDocument();
  });

  it("applies primary variant by default", () => {
    render(<Button>Primary</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toHaveClass("bg-brand-600");
  });

  it("applies danger variant", () => {
    render(<Button variant="danger">Delete</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toHaveClass("bg-red-600");
  });

  it("applies outline variant", () => {
    render(<Button variant="outline">Outline</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toHaveClass("border");
  });

  it("applies size sm", () => {
    render(<Button size="sm">Small</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toHaveClass("text-xs");
  });

  it("supports disabled state", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});

describe("Badge", () => {
  it("renders with text", () => {
    render(<Badge>Status</Badge>);
    expect(screen.getByText("Status")).toBeInTheDocument();
  });

  it("applies success variant", () => {
    render(<Badge variant="success">OK</Badge>);
    expect(screen.getByText("OK")).toHaveClass("text-emerald-400");
  });

  it("applies danger variant", () => {
    render(<Badge variant="danger">Error</Badge>);
    expect(screen.getByText("Error")).toHaveClass("text-red-400");
  });
});

describe("StatusBadge", () => {
  it("maps COMPLETE to success", () => {
    render(<StatusBadge status="COMPLETE" />);
    const el = screen.getByText("COMPLETE");
    expect(el).toHaveClass("text-emerald-400");
  });

  it("maps REJECTED to danger", () => {
    render(<StatusBadge status="REJECTED" />);
    const el = screen.getByText("REJECTED");
    expect(el).toHaveClass("text-red-400");
  });

  it("uppercases the status text", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("RUNNING")).toBeInTheDocument();
  });
});

describe("Input", () => {
  it("renders with label", () => {
    render(<Input label="Name" />);
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
  });

  it("renders without label", () => {
    render(<Input placeholder="Type..." />);
    expect(screen.getByPlaceholderText("Type...")).toBeInTheDocument();
  });
});

describe("Select", () => {
  it("renders options", () => {
    render(
      <Select
        label="Side"
        options={[
          { value: "BUY", label: "BUY" },
          { value: "SELL", label: "SELL" },
        ]}
      />,
    );
    expect(screen.getByLabelText("Side")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
  });
});

describe("MetricCard", () => {
  it("renders title and value", () => {
    render(<MetricCard title="Total" value="42" />);
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders subtitle when provided", () => {
    render(<MetricCard title="P&L" value="₹100" subtitle="Today" />);
    expect(screen.getByText("Today")).toBeInTheDocument();
  });
});

describe("ProgressBar", () => {
  it("renders with label", () => {
    render(<ProgressBar value={0.5} label="50% done" />);
    expect(screen.getByText("50% done")).toBeInTheDocument();
  });

  it("renders progressbar role", () => {
    render(<ProgressBar value={0.75} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "75");
  });

  it("clamps values to 0–100%", () => {
    render(<ProgressBar value={1.5} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "100");
  });
});

describe("PageHeader", () => {
  it("renders title", () => {
    render(<PageHeader title="Orders" />);
    expect(screen.getByText("Orders")).toBeInTheDocument();
  });

  it("renders subtitle", () => {
    render(<PageHeader title="Orders" subtitle="Manage orders" />);
    expect(screen.getByText("Manage orders")).toBeInTheDocument();
  });

  it("renders action", () => {
    render(
      <PageHeader title="T" action={<button>Action</button>} />,
    );
    expect(screen.getByRole("button", { name: "Action" })).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("renders title and description", () => {
    render(<EmptyState title="No data" description="Nothing here" />);
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("renders custom icon", () => {
    render(<EmptyState icon="🔍" title="Empty" />);
    expect(screen.getByText("🔍")).toBeInTheDocument();
  });
});
