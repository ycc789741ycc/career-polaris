import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { isPrivacyPath, PrivacyPolicy } from "./PrivacyPolicy";

describe("the privacy policy", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => {
    delete window.__APP_CONFIG__;
  });

  it("is served at /privacy, with or without a trailing slash", () => {
    expect(isPrivacyPath("/privacy")).toBe(true);
    expect(isPrivacyPath("/privacy/")).toBe(true);
    expect(isPrivacyPath("/")).toBe(false);
    expect(isPrivacyPath("/privacy-other")).toBe(false);
  });

  it("names the configured contact for requests about personal data", () => {
    render(<PrivacyPolicy />);
    const links = screen.getAllByRole("link", {
      name: "privacy@example.test",
    });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "mailto:privacy@example.test");
    }
  });

  it("says what Jira access is read and how to remove it", () => {
    render(<PrivacyPolicy />);
    expect(screen.getByText("read:jira-work")).toBeInTheDocument();
    expect(
      screen.getByText(/Disconnecting GitHub or Jira/).closest("li"),
    ).toHaveTextContent(/deletes its access tokens and every fact/);
  });
});
