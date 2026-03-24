import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { GlassCard } from "@/components/ui/GlassCard";

describe("GlassCard", () => {
  it("renders children content", () => {
    render(<GlassCard>Hello World</GlassCard>);
    expect(screen.getByText("Hello World")).toBeDefined();
  });

  it("applies glass-card base class", () => {
    const { container } = render(<GlassCard>Content</GlassCard>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("glass-card");
  });

  it("applies hover class when hover prop is true", () => {
    const { container } = render(<GlassCard hover>Hoverable</GlassCard>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("hover:border-accent-blue/30");
  });

  it("applies custom className", () => {
    const { container } = render(
      <GlassCard className="my-custom">Test</GlassCard>
    );
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("my-custom");
  });
});
