import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StatusBadge } from "@/components/ui/StatusBadge";

describe("StatusBadge", () => {
  it("renders the status text with underscores replaced by spaces", () => {
    render(<StatusBadge status="OCR_COMPLETE" />);
    expect(screen.getByText("OCR COMPLETE")).toBeDefined();
  });

  it("renders simple status unchanged", () => {
    render(<StatusBadge status="COMPLETE" />);
    expect(screen.getByText("COMPLETE")).toBeDefined();
  });

  it("applies custom className", () => {
    const { container } = render(
      <StatusBadge status="FAILED" className="custom-class" />
    );
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("custom-class");
  });
});
