import { describe, expect, it } from "vitest";
import { formatINR, formatINRShort, reasonLabel } from "./format";

describe("formatINR", () => {
  it("formats paise as Indian rupees", () => {
    expect(formatINR(50000000)).toBe("₹5,00,000.00");
    expect(formatINR(1660715)).toBe("₹16,607.15");
  });

  it("handles absent values without inventing a number", () => {
    expect(formatINR(null)).toBe("—");
    expect(formatINR(undefined)).toBe("—");
  });
});

describe("formatINRShort", () => {
  it("abbreviates lakh and crore", () => {
    expect(formatINRShort(50000000)).toBe("₹5.00 lakh");
    expect(formatINRShort(1000000000)).toBe("₹1.00 cr");
  });
});

describe("reasonLabel", () => {
  it("maps policy codes to readable text", () => {
    expect(reasonLabel("credit_score_below_min")).toBe("Credit score below our minimum");
  });

  it("falls back to the raw code rather than dropping it", () => {
    expect(reasonLabel("some_new_code")).toBe("some new code");
  });
});
