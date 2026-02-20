import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { KPICard } from "@/components/ui/KPICard";

describe("KPICard", () => {
  it("renders label and value", () => {
    render(
      <KPICard
        label="Total Scripts"
        value={42}
        icon={<span data-testid="icon">I</span>}
      />
    );
    expect(screen.getByText("Total Scripts")).toBeDefined();
    expect(screen.getByText("42")).toBeDefined();
  });

  it("renders trend text when provided", () => {
    render(
      <KPICard
        label="Score"
        value="85%"
        icon={<span>I</span>}
        trend="+5% from yesterday"
      />
    );
    expect(screen.getByText("+5% from yesterday")).toBeDefined();
  });

  it("renders the icon", () => {
    render(
      <KPICard
        label="Test"
        value={0}
        icon={<span data-testid="test-icon">Icon</span>}
      />
    );
    expect(screen.getByTestId("test-icon")).toBeDefined();
  });
});
