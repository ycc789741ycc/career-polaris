import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { APP_ICON_COLOURS, AppIcon, type AppIconVariant } from "./AppIcon";

describe("app icon", () => {
  it.each(Object.keys(APP_ICON_COLOURS) as AppIconVariant[])(
    "draws the %s version in its colours",
    (variant) => {
      const { container } = render(<AppIcon variant={variant} />);
      const colours = APP_ICON_COLOURS[variant];

      expect(container.querySelector("rect")).toHaveAttribute(
        "fill",
        colours.tile,
      );
      expect(container.querySelector("circle")).toHaveAttribute(
        "fill",
        colours.line,
      );
      const [path, star] = container.querySelectorAll("path");
      expect(path).toHaveAttribute("stroke", colours.line);
      expect(star).toHaveAttribute("fill", colours.star);
    },
  );

  it("is decorative unless it is given a name", () => {
    const { container, rerender } = render(<AppIcon />);
    expect(container.querySelector("svg")).toHaveAttribute(
      "aria-hidden",
      "true",
    );

    rerender(<AppIcon label="CareerPolaris" />);
    expect(screen.getByRole("img", { name: "CareerPolaris" })).toBeVisible();
  });
});
