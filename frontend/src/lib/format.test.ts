import { describe, expect, it } from "vitest";
import { formatClock, interviewTypeLabel, signed, titleCase } from "./format";

describe("format", () => {
  it("formats clocks and clamps negatives", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(605.9)).toBe("10:05");
    expect(formatClock(-3)).toBe("0:00");
  });

  it("labels", () => {
    expect(titleCase("llm_evaluation")).toBe("LLM evaluation");
    expect(titleCase("apis_fastapi")).toBe("APIs FastAPI");
    expect(titleCase("impact_ownership")).toBe("Impact ownership");
    expect(interviewTypeLabel("system_design")).toBe("System design");
    expect(interviewTypeLabel("hr")).toBe("HR");
    expect([signed(5), signed(-2), signed(0)]).toEqual(["+5", "-2", "0"]);
  });
});
