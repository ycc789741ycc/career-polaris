import { describe, expect, it } from "vitest";
import type { ResumeTemplateLimits, ResumeTemplateSpec } from "../api/types";
import { describeReading, getContrast, specProblem } from "./ResumeTemplates";

const spec: ResumeTemplateSpec = {
  layout: "single_column",
  heading_font: "Caprasimo",
  body_font: "Figtree",
  accent_color: "#c67139",
  name_color: "#8a4a20",
  text_color: "#201e1d",
  rule_color: "#c67139",
  rule: "thick",
  name_pt: 22,
  heading_pt: 8.5,
  body_pt: 10,
  sidebar_kinds: [],
  heading_case: "upper",
  bullet: "dot",
};

const limits: ResumeTemplateLimits = {
  fonts: ["Caprasimo", "Figtree", "DejaVu Serif", "DejaVu Sans Mono"],
  name_pt_range: [16, 30],
  heading_pt_range: [7, 11],
  body_pt_range: [8.5, 11.5],
  min_contrast: 4.5,
  max_name: 60,
  max_templates: 10,
  upload_max_bytes: 5_242_880,
};

describe("a template's checks, before the server's", () => {
  it("measures contrast as WCAG does", () => {
    expect(getContrast("#000000")).toBeCloseTo(21);
    expect(getContrast("#ffffff")).toBeCloseTo(1);
  });

  it("passes the built-in look and names what is wrong otherwise", () => {
    expect(specProblem("Mine", spec, limits)).toBeNull();
    expect(specProblem("  ", spec, limits)).toBe("Give the template a name.");
    expect(
      specProblem("Mine", { ...spec, name_color: "#ffff00" }, limits),
    ).toBe("The name is too light to read on a white page.");
    expect(specProblem("Mine", { ...spec, body_pt: 14 }, limits)).toBe(
      "Body size is from 8.5 to 11.5pt.",
    );
  });
});

describe("what a file's reading says it found", () => {
  it("names what was read and only that", () => {
    expect(
      describeReading({ ...spec, layout: "sidebar_left" }, [
        "layout",
        "accent_color",
      ]),
    ).toBe("We read: a left sidebar and its accent colour.");
    expect(describeReading(spec, [])).toBe("We could read little from it.");
  });
});
