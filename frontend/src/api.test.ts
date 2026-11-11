import { describe, expect, it } from "vitest";
import { errorMessage } from "./api";

describe("errorMessage", () => {
  it("passes handled errors through", () => {
    expect(errorMessage("Resume parsing failed: the AI provider account has no credit left.")).toContain("no credit");
  });

  it("turns validation issues into readable text instead of 'Unprocessable Entity'", () => {
    const email = [{ loc: ["body", "email"], msg: "value is not a valid email address: The part after the @-sign is a special-use or reserved name" }];
    expect(errorMessage(email)).toBe("Email: is not a valid email address");
    const jd = [{ loc: ["body", "raw_text"], msg: "String should have at least 50 characters" }];
    expect(errorMessage(jd)).toBe("Job description: String should have at least 50 characters");
  });

  it("returns null when there is nothing usable", () => {
    expect(errorMessage(undefined)).toBeNull();
    expect(errorMessage([])).toBeNull();
  });
});
