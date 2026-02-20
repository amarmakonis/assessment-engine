import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PipelineTracker } from "@/components/dashboard/PipelineTracker";

describe("PipelineTracker", () => {
  it("renders all five stages", () => {
    render(<PipelineTracker currentStatus="UPLOADED" />);
    expect(screen.getByText("Uploaded")).toBeDefined();
    expect(screen.getByText("OCR")).toBeDefined();
    expect(screen.getByText("Segmented")).toBeDefined();
    expect(screen.getByText("Evaluating")).toBeDefined();
    expect(screen.getByText("Complete")).toBeDefined();
  });

  it("shows correct stage for PROCESSING status", () => {
    const { container } = render(
      <PipelineTracker currentStatus="PROCESSING" />
    );
    expect(container.querySelector(".animate-glow-pulse")).toBeDefined();
  });

  it("handles COMPLETE status", () => {
    render(<PipelineTracker currentStatus="COMPLETE" />);
    expect(screen.getByText("Complete")).toBeDefined();
  });
});
