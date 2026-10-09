import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ResumeContent,
  ResumeSection,
  ResumeSummary,
  ResumeTemplateLimits,
  ResumeTemplateLook,
  ResumeTemplateSpec,
  TailoredResume,
} from "../api/types";
import type { AdvisorTarget } from "./target";
import { ShellContext, type Shell } from "../shell/ShellContext";
import { ToastProvider } from "../shell/toast";
import { startDownload } from "./download";
import {
  citeLine,
  coverageStatus,
  getStackWith,
  pageStyle,
  Resume,
  savedLine,
  trimmedNote,
} from "./Resume";

vi.mock("./download", () => ({ startDownload: vi.fn() }));

const matched: AdvisorTarget = {
  ref: { role_id: "r1", job_posting_id: "p1" },
  label: "Senior Backend Engineer · Northwind Pay",
  roleName: "Senior Backend Engineer",
  company: "Northwind Pay",
  location: null,
  postingTitle: "Senior Backend Engineer",
  url: null,
  creditedTo: null,
  fit: 88,
  band: "USD 178k–196k",
  isOwnPosting: false,
};

function section(
  kind: ResumeSection["kind"],
  fields: Partial<ResumeSection> = {},
): ResumeSection {
  return {
    kind,
    title: null,
    text: "",
    entries: [],
    items: [],
    bullets: [],
    is_shown: true,
    ...fields,
  };
}

const experience = (content: ResumeContent) =>
  content.sections.find((s) => s.kind === "experience")!;

const summary: ResumeSummary = {
  id: "res-1",
  target: { role_id: "r1", job_posting_id: "p1" },
  label: matched.label,
  status: "ready",
  error: null,
  latest_version: 1,
  created_at: "2026-09-20T10:00:00Z",
  updated_at: "2026-09-20T10:00:00Z",
};

const version = {
  id: "v1",
  number: 1,
  label: matched.label,
  source: "generated" as const,
  model_id: "claude-opus-5",
  created_at: "2026-09-20T10:00:00Z",
};

const resume: TailoredResume = {
  ...summary,
  template: "organic",
  options: { metrics: true, reorder: true, trim: false },
  snapshot: {
    title: "Senior Backend Engineer",
    company: "Northwind Pay",
    role_name: "Senior Backend Engineer",
    fit: 88,
    basis: "role",
  },
  coverage: [
    {
      requirement: "Own a high-throughput payments service",
      verdict: "covered",
      evidence: [
        { id: "e1", reference: "GitHub · 38 PRs", fact: "payments-svc" },
      ],
      answers: [],
    },
    {
      requirement: "Kubernetes in production",
      verdict: "gap",
      evidence: [],
      answers: [],
    },
    {
      requirement: "On-call for a payments platform",
      verdict: "gap",
      evidence: [],
      answers: [
        {
          id: "e9",
          reference: "Your answer",
          fact: "Were you on call? — Yes, weekly for two years",
        },
      ],
    },
  ],
  version,
  content: {
    name: "Maya Lin Chen",
    headline: "Backend Engineer",
    contacts: [{ kind: "email", value: "maya@example.com" }],
    sections: [
      section("summary", { text: "Builds payment systems." }),
      section("experience", {
        entries: [
          {
            title: "Backend Engineer",
            org: "Kestrel Financial",
            when: "2022 — now",
            link: "",
            bullets: [
              {
                text: "Owned the retry layer for payments-svc",
                evidence_ids: ["e1"],
                origin: "written",
                answers: "Own a high-throughput payments service",
              },
            ],
          },
        ],
      }),
      section("skills", { items: ["Go", "Postgres", "Kafka", "gRPC"] }),
      // Written with the rest, and hidden (ADR 0043).
      section("open_source", {
        is_shown: false,
        entries: [
          {
            title: "pgx",
            org: "",
            when: "2024",
            link: "",
            bullets: [
              {
                text: "Fixed a pool leak in pgx",
                evidence_ids: ["e1"],
                origin: "written",
                answers: null,
              },
            ],
          },
        ],
      }),
      section("education", { is_shown: false }),
    ],
  },
  heading_font: null,
  body_font: null,
  section_plan: [
    { kind: "summary", title: null, is_shown: true },
    { kind: "experience", title: null, is_shown: true },
    { kind: "skills", title: null, is_shown: true },
    { kind: "open_source", title: null, is_shown: false },
    { kind: "education", title: null, is_shown: false },
  ],
  evidence: { e1: { reference: "GitHub · 38 PRs", fact: "payments-svc" } },
  versions: [version],
  revisions: [],
  is_outdated: false,
  outdated_by: [],
};

function json(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status: body === undefined ? 204 : status,
    headers: { "Content-Type": "application/json" },
  });
}

function sse(events: [string, unknown][]): Response {
  const text = events
    .map(
      ([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`,
    )
    .join("");
  return new Response(
    new ReadableStream({
      start(controller) {
        const bytes = new TextEncoder().encode(text);
        // Split mid-event, as a network would.
        controller.enqueue(bytes.slice(0, 20));
        controller.enqueue(bytes.slice(20));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

const organic: ResumeTemplateLook = {
  id: "organic",
  name: "Organic",
  note: "Rounded, terracotta rule.",
  is_built_in: true,
  spec: {
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
  },
  rule: "3px solid #c67139",
  band_color: "#f8ede6",
  title_pt: 11,
  contact_pt: 9.5,
  small_pt: 9,
  page_width_mm: 210,
  page_height_mm: 297,
  margin_top_mm: 18,
  margin_side_mm: 17,
  trimmed_bullets: 3,
  trimmed_skills: 12,
};

const templates = {
  items: [
    organic,
    {
      ...organic,
      id: "plain",
      name: "Plain",
      note: "One page, evidence first.",
      rule: "1px solid #cfcac5",
    },
  ],
  page: 1,
  page_size: null,
  total: 2,
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
  contact_icons: {
    email: "M0 0h24v24H0z",
    phone: "M0 0h24v24H0z",
    github: "M0 0h24v24H0z",
    linkedin: "M0 0h24v24H0z",
    website: "M0 0h24v24H0z",
    location: "M0 0h24v24H0z",
  },
};

type Call = { method: string; url: string; body: unknown };

function serve(route: (call: Call) => Response | unknown) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call = {
        method: init?.method ?? "GET",
        url: String(input).replace("http://api.test/api/v1", ""),
        body:
          typeof init?.body === "string"
            ? JSON.parse(init.body)
            : (init?.body ?? undefined),
      };
      calls.push(call);
      // The templates, as the renderer draws them: every screen reads them.
      const result =
        call.method === "GET" && call.url.startsWith("/resume-templates")
          ? call.url === "/resume-templates/limits"
            ? limits
            : templates
          : route(call);
      return result instanceof Response ? result : json(result);
    }),
  );
  return calls;
}

function defaults(call: Call): unknown {
  if (call.url === "/tailored-resumes/res-1") return resume;
  return null;
}

function renderResume(saved: ResumeSummary[] = [summary]) {
  const onChanged = vi.fn();
  const onRevisit = vi.fn();
  const shell: Shell = {
    status: {
      me: null,
      credential: {
        provider: "anthropic",
        model: "claude-opus-5",
        base_url: null,
        last_four: "abcd",
        status: "active",
        last_error: null,
      },
    },
    navigate: vi.fn(),
    focus: null,
    setFocus: vi.fn(),
    refresh: async () => {},
    target: null,
    setTarget: vi.fn(),
    account: "maya@example.com",
    setHeading: vi.fn(),
  };
  render(
    <ShellContext.Provider value={shell}>
      <ToastProvider>
        <Resume
          target={matched}
          saved={saved}
          onChanged={onChanged}
          onRevisit={onRevisit}
        />
      </ToastProvider>
    </ShellContext.Provider>,
  );
  return { shell, onChanged, onRevisit };
}

describe("résumé screen", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is laid out as the prototype: the tools beside the page, coverage collapsed", async () => {
    serve((call) =>
      call.url.startsWith("/tailored-resumes/cost-estimate")
        ? {
            cost_usd: "0.04",
            model_id: "claude-opus-5",
            rate_is_published: true,
          }
        : defaults(call),
    );
    renderResume();

    await screen.findByRole("article", { name: "Résumé" });
    const tools = screen.getByRole("complementary", { name: "Résumé tools" });
    const cards = [...tools.querySelectorAll(":scope > details")];
    expect(
      cards.map((card) => card.querySelector("summary > span")?.textContent),
    ).toEqual(["Layout", "Revise with AI", "Coverage"]);
    // Layout and Revise open, Coverage closed, as the prototype has them.
    expect(cards.map((card) => card.hasAttribute("open"))).toEqual([
      true,
      true,
      false,
    ]);
    expect(within(cards[0] as HTMLElement).getByText("Template")).toBeVisible();
    expect(
      within(cards[0] as HTMLElement).getByRole("region", { name: "Sections" }),
    ).toBeInTheDocument();
    // No third column: the requirements are the Coverage card.
    expect(document.querySelector(".resume-col-requirements")).toBeNull();

    // "Regenerate résumé" sits on the Write-for card, with what it costs.
    expect(
      screen.getByRole("button", { name: "Regenerate résumé" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        /about \$0\.04 on your key · saved as a new version/,
      ),
    ).toBeInTheDocument();

    // Each requirement's evidence is collapsed behind "Evidence ▾".
    const requirements = cards[2]!.querySelector(".tool-card-body")!;
    const disclosures = requirements.querySelectorAll("details");
    expect(disclosures.length).toBeGreaterThan(0);
    disclosures.forEach((d) => expect(d).not.toHaveAttribute("open"));
    expect(
      within(requirements as HTMLElement).getAllByText("Evidence ▾").length,
    ).toBe(disclosures.length);
  });

  it("picks a saved résumé from the Version list, and moves to its target", async () => {
    serve(defaults);
    const user = userEvent.setup();
    const elsewhere: ResumeSummary = {
      ...summary,
      id: "res-2",
      target: { role_id: null, private_job_posting_id: "j1" },
      label: "Principal Engineer · Halden Labs",
      latest_version: 3,
      updated_at: "2026-09-12T10:00:00Z",
    };
    const { onRevisit } = renderResume([summary, elsewhere]);

    await screen.findByRole("article", { name: "Résumé" });
    const versions = screen.getByRole("combobox", { name: "Version" });
    expect(versions).toHaveValue("res-1");
    expect(
      within(versions).getByRole("option", {
        name: "Principal Engineer · Halden Labs · v3 · edited 12 Sep 2026",
      }),
    ).toBeInTheDocument();
    await user.selectOptions(versions, "res-2");
    expect(onRevisit).toHaveBeenCalledWith(elsewhere);
  });

  it("exports from beside the page, once the edits are saved", async () => {
    serve(defaults);
    renderResume();

    await screen.findByRole("article", { name: "Résumé" });
    const actions = document.querySelector(
      ".resume-col-page .resume-page-actions",
    );
    expect(
      within(actions as HTMLElement).getByRole("button", {
        name: "Export as PDF",
      }),
    ).toBeEnabled();
    expect(
      within(actions as HTMLElement).getByRole("button", {
        name: /^Save as v\d+$/,
      }),
    ).toBeDisabled();
  });

  it("opens the latest résumé with cited lines and coverage", async () => {
    serve(defaults);
    const user = userEvent.setup();
    renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    expect(within(page).getByText("Maya Lin Chen")).toBeInTheDocument();
    const note = within(page).getByText(
      "GitHub · 38 PRs — answers “Own a high-throughput payments service”",
    );
    // Where a line came from is the app's note, not the page's: hidden until
    // asked for, so the page lays out as it prints.
    expect(note).not.toBeVisible();
    await user.click(
      screen.getByRole("checkbox", { name: "Show where each line came from" }),
    );
    expect(note).toBeVisible();
    expect(screen.getByText("Covered")).toBeInTheDocument();
    expect(screen.getAllByText("Gap")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /^Save as v\d+$/ }),
    ).toBeDisabled();
  });

  it("sets the résumé in fonts of its own and previews them", async () => {
    const calls = serve(defaults);
    const user = userEvent.setup();
    renderResume();
    await screen.findByRole("article", { name: "Résumé" });

    const titles = await screen.findByRole("combobox", { name: "Titles in" });
    expect(titles).toHaveValue("");
    await user.selectOptions(titles, "DejaVu Serif");

    expect(calls).toContainEqual(
      expect.objectContaining({
        method: "PUT",
        url: "/tailored-resumes/res-1/settings",
        body: expect.objectContaining({
          heading_font: "DejaVu Serif",
          body_font: null,
        }),
      }),
    );
    const page = screen.getByRole("article", { name: "Résumé" });
    expect(page.getAttribute("style")).toContain("DejaVu Serif");
  });

  it("writes a failed résumé again once priced", async () => {
    let regenerated = false;
    const calls = serve((call) => {
      if (call.url.startsWith("/tailored-resumes/cost-estimate"))
        return { cost_usd: "0.05", model_id: "claude-opus-5" };
      if (call.url === "/tailored-resumes/res-1/regenerate") {
        regenerated = true;
        return { ...summary, status: "drafting" };
      }
      if (call.url === "/tailored-resumes/res-1")
        return regenerated
          ? { ...resume, status: "drafting" }
          : {
              ...resume,
              status: "failed",
              error: {
                code: "ai_output_invalid",
                message: "the written résumé was rejected",
              },
              version: null,
              versions: [],
              content: null,
            };
      return null;
    });
    const user = userEvent.setup();
    renderResume();

    expect(
      await screen.findByText("This résumé could not be written"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Run it" }));

    expect(calls).toContainEqual({
      method: "POST",
      url: "/tailored-resumes/res-1/regenerate",
      body: undefined,
    });
  });

  it("regenerates an outdated résumé as its next version once priced", async () => {
    let regenerated = false;
    const calls = serve((call) => {
      if (call.url.startsWith("/tailored-resumes/cost-estimate"))
        return { cost_usd: "0.05", model_id: "claude-opus-5" };
      if (call.url === "/tailored-resumes/res-1/regenerate") {
        regenerated = true;
        return { ...summary, status: "drafting" };
      }
      if (call.url === "/tailored-resumes/res-1")
        return regenerated
          ? { ...resume, status: "drafting" }
          : { ...resume, is_outdated: true, outdated_by: ["evidence"] };
      return null;
    });
    const user = userEvent.setup();
    renderResume();

    const banner = await screen.findByRole("status", { name: "Outdated" });
    expect(banner).toHaveTextContent("Outdated: your evidence changed");
    await user.click(
      within(banner).getByRole("button", { name: "Regenerate" }),
    );
    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(confirm).toHaveTextContent("Writing the résumé again for");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Run it" }));

    expect(calls).toContainEqual({
      method: "POST",
      url: "/tailored-resumes/res-1/regenerate",
      body: undefined,
    });
    expect(
      calls.some((c) => c.url === "/tailored-resumes" && c.method === "POST"),
    ).toBe(false);
  });

  it("removes one entry from a section, kept until the version is saved", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    const remove = within(page).getByRole("button", {
      name: "Remove Backend Engineer from Experience",
    });
    // On the left of the entry's title.
    expect(
      remove.compareDocumentPosition(
        within(page).getAllByLabelText("Title")[0]!,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await user.click(remove);

    // Gone from the page, and nothing saved until asked.
    expect(
      within(page).queryByText("Owned the retry layer for payments-svc"),
    ).toBeNull();
    expect(
      calls.some((c) => c.url === "/tailored-resumes/res-1/versions"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: /^Save as v\d+$/ }));

    const saved = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/versions",
    );
    const body = saved?.body as { content: ResumeContent };
    expect(experience(body.content).entries).toEqual([]);
  });

  it("undoes unsaved edits one at a time, back to the saved version", async () => {
    const calls = serve(defaults);
    const user = userEvent.setup();
    renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    const undo = screen.getByRole("button", { name: "Undo" });
    expect(undo).toBeDisabled();

    // Two edits: a line rewritten, then the entry removed.
    const line = within(page).getByText(
      "Owned the retry layer for payments-svc",
    );
    line.textContent = "Owned the retry layer, end to end";
    fireEvent.blur(line);
    await user.click(
      within(page).getByRole("button", {
        name: "Remove Backend Engineer from Experience",
      }),
    );
    expect(within(page).queryByText(/Owned the retry layer/)).toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Undo (2 unsaved edits)" }),
    );
    expect(
      within(page).getByText("Owned the retry layer, end to end"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Undo (1 unsaved edit)" }),
    );
    expect(
      within(page).getByText("Owned the retry layer for payments-svc"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    // Back where it was saved: nothing to save, and nothing was sent.
    expect(
      screen.getByRole("button", { name: /^Save as v\d+$/ }),
    ).toBeDisabled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("undoes the last edit with the keyboard when no line is being typed in", async () => {
    serve(defaults);
    const user = userEvent.setup();
    renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    await user.click(
      within(page).getByRole("button", {
        name: "Remove Backend Engineer from Experience",
      }),
    );
    (document.activeElement as HTMLElement | null)?.blur();
    await user.keyboard("{Control>}z{/Control}");

    expect(
      within(page).getByText("Owned the retry layer for payments-svc"),
    ).toBeInTheDocument();
  });

  it("saves an edited line as a new version", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    const line = await screen.findByText(
      "Owned the retry layer for payments-svc",
    );
    line.textContent = "Owned the retry layer, end to end";
    fireEvent.blur(line);

    const save = screen.getByRole("button", { name: /^Save as v\d+$/ });
    expect(save).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Export as PDF" }),
    ).toBeDisabled();
    await user.click(save);

    const posted = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/versions",
    );
    const body = posted?.body as { content: ResumeContent };
    expect(experience(body.content).entries[0]!.bullets[0]!.text).toBe(
      "Owned the retry layer, end to end",
    );
  });

  it("edits the headline, a heading, an entry's fields and a skill in place", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();
    await screen.findByRole("article", { name: "Résumé" });

    const type = (label: string, text: string) => {
      const field = screen.getByLabelText(label);
      field.textContent = text;
      fireEvent.blur(field);
    };
    type("Headline", "Staff Backend Engineer");
    type("Email contact", "maya.chen@example.com");
    type("Heading of Experience", "Work history");
    type("Title", "Senior Backend Engineer");
    type("Organisation", "Kestrel");
    type("When", "2021 — now");
    type("Link", "kestrel.example");
    // Renamed, the heading's own label follows it.
    expect(screen.getByLabelText("Heading of Work history")).toBeTruthy();
    const [go] = screen.getAllByLabelText("Skills item");
    go!.textContent = "Golang";
    fireEvent.blur(go!);
    const [, postgres] = screen.getAllByLabelText("Skills item");
    postgres!.textContent = "";
    fireEvent.blur(postgres!);

    await user.click(screen.getByRole("button", { name: /^Save as v\d+$/ }));

    const body = calls.find((c) => c.url === "/tailored-resumes/res-1/versions")
      ?.body as { content: ResumeContent };
    expect(body.content.headline).toBe("Staff Backend Engineer");
    expect(body.content.contacts).toEqual([
      { kind: "email", value: "maya.chen@example.com" },
    ]);
    const work = experience(body.content);
    expect(work.title).toBe("Work history");
    expect(work.entries[0]).toMatchObject({
      title: "Senior Backend Engineer",
      org: "Kestrel",
      when: "2021 — now",
      link: "kestrel.example",
    });
    const skills = body.content.sections.find((s) => s.kind === "skills")!;
    expect(skills.items).toEqual(["Golang", "Kafka", "gRPC"]);
  });

  it("draws each contact detail with its icon and changes its kind", async () => {
    const calls = serve((call) => {
      if (call.url === "/tailored-resumes/res-1/versions")
        return { ...version, id: "v2", number: 2, source: "manual" };
      return defaults(call);
    });
    const user = userEvent.setup();
    renderResume();
    const page = await screen.findByRole("article", { name: "Résumé" });

    expect(page.querySelectorAll(".resume-contact-icon")).toHaveLength(1);
    await user.selectOptions(
      screen.getByLabelText("Kind of maya@example.com"),
      "website",
    );
    await user.click(screen.getByRole("button", { name: "+ Add contact" }));
    await user.click(screen.getByRole("button", { name: /^Save as v\d+$/ }));

    const body = calls.find((c) => c.url === "/tailored-resumes/res-1/versions")
      ?.body as { content: ResumeContent };
    expect(body.content.contacts).toEqual([
      { kind: "website", value: "maya@example.com" },
      { kind: "email", value: "you@example.com" },
    ]);
  });

  it("puts a cleared heading back to its kind's own", async () => {
    serve(defaults);
    renderResume();
    await screen.findByRole("article", { name: "Résumé" });

    const renamed = screen.getByLabelText("Heading of Summary");
    renamed.textContent = "Profile";
    fireEvent.blur(renamed);
    const cleared = screen.getByLabelText("Heading of Profile");
    cleared.textContent = "";
    fireEvent.blur(cleared);

    expect(screen.getByLabelText("Heading of Summary")).toHaveTextContent(
      "Summary",
    );
  });

  it("writes for the target it is aimed at once the price is confirmed", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/tailored-resumes/cost-estimate"))
        return { cost_usd: "0.05", model_id: "claude-opus-5" };
      if (call.url === "/tailored-resumes" && call.method === "POST")
        return { ...summary, status: "drafting" };
      if (call.url === "/tailored-resumes/res-1")
        return { ...resume, status: "drafting", content: null };
      return null;
    });
    const user = userEvent.setup();
    const { onChanged } = renderResume([]);

    await user.click(
      await screen.findByRole("button", {
        name: "Write résumé for Senior Backend Engineer",
      }),
    );
    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(calls.map((c) => c.url)).toContain(
      "/tailored-resumes/cost-estimate?role_id=r1&job_posting_id=p1",
    );
    await user.click(within(confirm).getByRole("button", { name: "Run it" }));

    expect(
      await screen.findByText(/Writing on claude-opus-5/),
    ).toBeInTheDocument();
    expect(calls).toContainEqual(
      expect.objectContaining({
        method: "POST",
        url: "/tailored-resumes",
        body: expect.objectContaining({ role_id: "r1", job_posting_id: "p1" }),
      }),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("streams a chat reply and applies its proposal only on request", async () => {
    const calls = serve((call) => {
      if (call.url === "/tailored-resumes/res-1/revisions")
        return sse([
          ["text", { text: "Shorter summary, " }],
          ["text", { text: "same lead line." }],
          [
            "proposal",
            {
              revision_id: "rev-1",
              reply: "Shorter summary, same lead line.",
              proposal: resume.content,
            },
          ],
        ]);
      if (call.url === "/tailored-resumes/res-1/revisions/rev-1/apply")
        return { ...version, id: "v2", number: 2, source: "chat" };
      return defaults(call);
    });
    const user = userEvent.setup();
    renderResume();

    await screen.findByRole("article", { name: "Résumé" });
    await user.click(
      screen.getByRole("button", { name: "Make the summary shorter" }),
    );

    expect(
      await screen.findByText("Shorter summary, same lead line."),
    ).toBeInTheDocument();
    const posted = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/revisions",
    );
    expect(posted?.body).toMatchObject({
      message: "Make the summary shorter",
      content: { name: "Maya Lin Chen" },
    });
    expect(calls.some((c) => c.url.endsWith("/apply"))).toBe(false);

    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(calls.some((c) => c.url.endsWith("/revisions/rev-1/apply"))).toBe(
      true,
    );
  });

  it("shows a rejected revision as an error, with nothing to apply", async () => {
    serve((call) =>
      call.url === "/tailored-resumes/res-1/revisions"
        ? sse([
            ["text", { text: "Added it." }],
            [
              "error",
              {
                code: "ai_output_invalid",
                message: "the proposed revision was rejected",
              },
            ],
          ])
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    // The chat opens once the résumé has loaded.
    await screen.findByRole("article", { name: "Résumé" });
    const input = screen.getByRole("textbox", { name: "Ask for a change" });
    expect(input).toBeEnabled();
    await user.type(input, "Add a promotion{Enter}");

    expect(
      await screen.findByText(/the proposed revision was rejected/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Apply" }),
    ).not.toBeInTheDocument();
  });
});

describe("the grey note under a line", () => {
  const evidence = { e1: { reference: "Jira PAY-412", fact: "…" } };

  it("names its source and what it answers", () => {
    expect(
      citeLine(
        { text: "x", evidence_ids: ["e1"], origin: "written", answers: "Lead" },
        evidence,
      ),
    ).toBe("Jira PAY-412 — answers “Lead”");
  });

  it("says plainly when a line is the user's own and cites nothing", () => {
    expect(
      citeLine(
        { text: "x", evidence_ids: [], origin: "yours", answers: null },
        evidence,
      ),
    ).toBe("Your edit — no source cited");
  });
});

describe("the page as it prints (ADR 0038)", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.mocked(startDownload).mockClear();
  });

  it("draws the template the renderer serves, in its picker and on the page", async () => {
    serve(defaults);
    renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    expect(page.style.getPropertyValue("--rule")).toBe("3px solid #c67139");
    expect(page.style.getPropertyValue("--name-pt")).toBe("22");
    expect(screen.getByRole("button", { name: /Plain/ })).toBeInTheDocument();
  });

  it("drops from the page what Trim to one page drops from the PDF", async () => {
    const long = {
      ...resume,
      options: { ...resume.options, trim: true },
      content: {
        ...resume.content!,
        sections: resume.content!.sections.map((s) =>
          s.kind === "experience"
            ? {
                ...s,
                entries: [
                  {
                    ...s.entries[0]!,
                    bullets: Array.from({ length: 5 }, (_, i) => ({
                      text: `Line ${i}`,
                      evidence_ids: ["e1"],
                      origin: "written" as const,
                      answers: null,
                    })),
                  },
                ],
              }
            : s,
        ),
      },
    };
    serve((call) => (call.url === "/tailored-resumes/res-1" ? long : null));
    renderResume();

    const page = await screen.findByRole("article", { name: "Résumé" });
    expect(within(page).getByText("Line 2")).toBeInTheDocument();
    expect(within(page).queryByText("Line 3")).toBeNull();
    expect(
      screen.getByText("Trimmed to one page: 2 lines left out of the PDF."),
    ).toBeInTheDocument();
  });

  it("downloads the PDF as soon as it is rendered, with no link to click", async () => {
    let polls = 0;
    serve((call) => {
      if (call.url === "/tailored-resumes/res-1/exports")
        return {
          id: "x1",
          version_id: "v1",
          template: "organic",
          status: "rendering",
          error: null,
          download_url: null,
        };
      if (call.url === "/resume-exports/x1") {
        polls += 1;
        return {
          id: "x1",
          version_id: "v1",
          template: "organic",
          status: "ready",
          error: null,
          download_url: "https://objects.test/x1.pdf?signed",
        };
      }
      return defaults(call);
    });
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderResume();

    await user.click(
      await screen.findByRole("button", { name: "Export as PDF" }),
    );
    await vi.advanceTimersByTimeAsync(2500);
    vi.useRealTimers();

    await vi.waitFor(() =>
      expect(startDownload).toHaveBeenCalledWith(
        "https://objects.test/x1.pdf?signed",
      ),
    );
    expect(polls).toBe(1);
    expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
  });
});

describe("the page's measures", () => {
  it("sets margins as a share of the page's width", () => {
    const style = pageStyle(organic);
    expect(style["--margin-side"]).toBe(`${(17 / 210) * 100}cqw`);
    expect(style["--page-ratio"]).toBe(String(297 / 210));
  });

  it("draws the template's choices: headings, bullets, colours", () => {
    const style = pageStyle({
      ...organic,
      spec: {
        ...organic.spec,
        heading_case: "as_written",
        bullet: "dash",
        text_color: "#333333",
      },
    });
    expect(style["--heading-case"]).toBe("none");
    expect(style["--bullet"]).toBe('"\\2013  "');
    expect(style["--text-color"]).toBe("#333333");
    expect(style["--dot-color"]).toBe("#c67139");
  });

  it("says what trimming leaves out, or that it leaves nothing", () => {
    const content = resume.content!;
    expect(
      trimmedNote(content, { ...resume.options, trim: false }, organic),
    ).toBe("As it will print, A4.");
    expect(
      trimmedNote(
        {
          ...content,
          sections: [
            section("skills", {
              items: Array.from({ length: 14 }, (_, i) => `S${i}`),
            }),
          ],
        },
        { ...resume.options, trim: true },
        organic,
      ),
    ).toBe("Trimmed to one page: 2 items left out of the PDF.");
  });
});

describe("templates of your own (ADR 0040)", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("previews a sidebar while it is made, then saves it and sets the résumé in it", async () => {
    const calls = serve((call) => {
      if (call.method === "POST" && call.url === "/resume-templates") {
        const body = call.body as { name: string; spec: ResumeTemplateSpec };
        return { ...organic, id: "t-1", is_built_in: false, ...body };
      }
      return defaults(call);
    });
    const user = userEvent.setup();
    renderResume();

    await user.click(
      await screen.findByRole("button", { name: "Make your own" }),
    );
    const editor = screen.getByRole("group", { name: "Make your own" });
    await user.selectOptions(
      within(editor).getByLabelText("Layout"),
      "sidebar_left",
    );
    await user.click(within(editor).getByRole("checkbox", { name: "Skills" }));

    const page = screen.getByRole("article", { name: "Résumé" });
    expect(page.dataset.layout).toBe("sidebar_left");
    const side = page.querySelector(".resume-side")!;
    expect(side.textContent).toContain("Skills");
    expect(page.querySelector(".resume-main")!.textContent).toContain(
      "Experience",
    );

    await user.click(screen.getByRole("button", { name: "Save template" }));

    await vi.waitFor(() =>
      expect(
        calls.find((c) => c.method === "PUT" && c.url.endsWith("/settings"))
          ?.body,
      ).toMatchObject({ template: "t-1" }),
    );
    const created = calls.find(
      (c) => c.method === "POST" && c.url === "/resume-templates",
    )!.body as { name: string; spec: ResumeTemplateSpec };
    expect(created.name).toBe("Organic — mine");
    expect(created.spec).toMatchObject({
      layout: "sidebar_left",
      sidebar_kinds: ["skills"],
    });
  });

  it("deletes your own template and leaves the résumé on Organic", async () => {
    const mine = { ...organic, id: "t-1", name: "Mine", is_built_in: false };
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1"
        ? { ...resume, template: "t-1" }
        : defaults(call),
    );
    templates.items.push(mine);
    try {
      const user = userEvent.setup();
      renderResume();

      await user.click(
        await screen.findByRole("button", { name: "Change Mine" }),
      );
      await user.click(
        screen.getByRole("button", { name: "Delete this template" }),
      );
      await user.click(screen.getByRole("button", { name: "Delete it" }));

      await vi.waitFor(() =>
        expect(screen.getByRole("button", { name: /Organic/ })).toHaveAttribute(
          "aria-pressed",
          "true",
        ),
      );
      expect(calls.some((c) => c.method === "DELETE")).toBe(true);
      expect(screen.queryByRole("button", { name: /Mine/ })).toBeNull();
    } finally {
      templates.items.pop();
    }
  });

  it("starts from a file: opens on its draft with read and defaulted values marked", async () => {
    const reading = {
      id: "r-1",
      status: "ready",
      error: null,
      spec: {
        ...organic.spec,
        layout: "sidebar_left",
        sidebar_kinds: ["skills"],
      },
      read: ["layout", "heading_font", "accent_color", "name_pt", "body_pt"],
      defaulted: ["bullet", "rule", "sidebar_kinds"],
      created_at: "2026-10-10T00:00:00+00:00",
    };
    const calls = serve((call) =>
      call.method === "POST" && call.url === "/resume-templates/upload"
        ? reading
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    await user.click(
      await screen.findByRole("button", { name: "Make your own" }),
    );
    await user.upload(
      screen.getByLabelText("Résumé PDF to start from"),
      new File(["%PDF-1.4"], "someone.pdf", { type: "application/pdf" }),
    );

    expect(
      await screen.findByText(/We read: a left sidebar, a display name/),
    ).toBeInTheDocument();
    const editor = screen.getByRole("group", { name: "Make your own" });
    expect(
      within(editor).getByLabelText("Layout — read from the file"),
    ).toHaveValue("sidebar_left");
    expect(
      within(editor).getByLabelText("Bullets — not read; Organic's, check it"),
    ).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Résumé" }).dataset.layout).toBe(
      "sidebar_left",
    );
    // Nothing is a template until it is saved.
    expect(
      calls.some((c) => c.method === "POST" && c.url === "/resume-templates"),
    ).toBe(false);
  });

  it("will not save text too light to read", async () => {
    serve(defaults);
    const user = userEvent.setup();
    renderResume();

    await user.click(
      await screen.findByRole("button", { name: "Make your own" }),
    );
    fireEvent.input(screen.getByLabelText("Text"), {
      target: { value: "#eeeeee" },
    });

    expect(
      await screen.findByText("The text is too light to read on a white page."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Save template" }),
    ).toBeDisabled();
  });
});

describe("sections you choose (ADR 0039, ADR 0043)", () => {
  beforeEach(() => {
    window.__APP_CONFIG__ = {
      apiBaseUrl: "http://api.test",
      privacyContactEmail: "privacy@example.test",
    };
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists every section, prints only the shown ones, and hiding one waits for Save", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    const panel = await screen.findByRole("region", { name: "Sections" });
    const rows = within(panel).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Summary"),
      expect.stringContaining("Experience"),
      expect.stringContaining("Skills"),
      expect.stringContaining("Open source"),
      expect.stringContaining("Education"),
    ]);
    expect(rows[1]).toHaveTextContent("Required");
    expect(within(rows[1]!).queryByRole("button", { name: "Hide" })).toBeNull();
    expect(within(rows[3]!).getByRole("button", { name: "Show" })).toBeTruthy();
    // Written, and not printed while hidden.
    expect(screen.queryByText("Fixed a pool leak in pgx")).toBeNull();

    await user.click(within(rows[2]!).getByRole("button", { name: "Hide" }));

    expect(calls.some((c) => c.url.includes("/sections"))).toBe(false);
    // Hidden on the page at once, and saved only when the user asks.
    expect(
      calls.some((c) => c.url === "/tailored-resumes/res-1/versions"),
    ).toBe(false);
    expect(
      screen.getByText("You have unsaved edits.", { exact: false }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^Save as v\d+$/ }));
    const saved = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/versions",
    );
    const body = saved?.body as { content: ResumeContent };
    expect(body.content.sections.map((s) => [s.kind, s.is_shown])).toEqual([
      ["summary", true],
      ["experience", true],
      ["skills", false],
      ["open_source", false],
      ["education", false],
    ]);
  });

  it("shows a hidden section at no cost", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    const panel = await screen.findByRole("region", { name: "Sections" });
    const row = within(panel).getAllByRole("listitem")[3]!;
    await user.click(within(row).getByRole("button", { name: "Show" }));
    expect(
      calls.some((c) => c.url === "/tailored-resumes/res-1/versions"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: /^Save as v\d+$/ }));

    const saved = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/versions",
    );
    const body = saved?.body as { content: ResumeContent };
    const shown = body.content.sections.find((s) => s.kind === "open_source");
    expect(shown?.is_shown).toBe(true);
    expect(shown?.entries[0]?.bullets[0]?.text).toBe(
      "Fixed a pool leak in pgx",
    );
    expect(calls.some((c) => c.url.includes("/sections"))).toBe(false);
  });

  it("moves a section with the keyboard, and saves the new order when asked", async () => {
    const calls = serve((call) =>
      call.url === "/tailored-resumes/res-1/versions"
        ? { ...version, id: "v2", number: 2, source: "manual" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    const handle = await screen.findByRole("button", { name: "Move Summary" });
    handle.focus();
    await user.keyboard("{ArrowDown}");
    await user.click(screen.getByRole("button", { name: /^Save as v\d+$/ }));

    const saved = calls.find(
      (c) => c.url === "/tailored-resumes/res-1/versions",
    );
    const body = saved?.body as { content: ResumeContent };
    expect(body.content.sections.map((s) => s.kind)).toEqual([
      "experience",
      "summary",
      "skills",
      "open_source",
      "education",
    ]);
  });

  it("asks to save first before filling a section over unsaved changes", async () => {
    const calls = serve(defaults);
    const user = userEvent.setup();
    renderResume();

    const panel = await screen.findByRole("region", { name: "Sections" });
    const rows = within(panel).getAllByRole("listitem");
    await user.click(within(rows[2]!).getByRole("button", { name: "Hide" }));
    await user.click(
      within(rows[4]!).getByRole("button", {
        name: "Empty — fill from your sources",
      }),
    );

    expect(
      await screen.findByText(
        "Save your changes first: a section is filled into the saved version.",
      ),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes("/sections/estimate"))).toBe(false);
  });

  it("prices filling an empty section before filling it", async () => {
    const calls = serve((call) => {
      if (call.url.startsWith("/tailored-resumes/res-1/sections/estimate"))
        return { cost_usd: "0.02", model_id: "claude-opus-5" };
      if (call.url === "/tailored-resumes/res-1/sections")
        return { ...summary, status: "filling" };
      return defaults(call);
    });
    const user = userEvent.setup();
    renderResume();

    const panel = await screen.findByRole("region", { name: "Sections" });
    const rows = within(panel).getAllByRole("listitem");
    // Only the empty section offers it.
    expect(
      within(rows[3]!).queryByRole("button", {
        name: "Empty — fill from your sources",
      }),
    ).toBeNull();
    await user.click(
      within(rows[4]!).getByRole("button", {
        name: "Empty — fill from your sources",
      }),
    );
    const confirm = await screen.findByRole("region", {
      name: "Cost estimate",
    });
    expect(confirm).toHaveTextContent("Filling Education from your sources");
    expect(calls.some((c) => c.method === "POST")).toBe(false);

    await user.click(within(confirm).getByRole("button", { name: "Run it" }));

    expect(calls).toContainEqual({
      method: "POST",
      url: "/tailored-resumes/res-1/sections",
      body: { kind: "education", title: null },
    });
  });

  it("marks a gap the user answered about, and lists the answer", async () => {
    serve(defaults);
    renderResume();

    const answered = (
      await screen.findByText("On-call for a payments platform")
    ).closest(".requirement-row") as HTMLElement;
    expect(within(answered).getByText("Answered by you")).toBeTruthy();
    expect(answered).toHaveTextContent("Yes, weekly for two years");
    const unanswered = screen
      .getByText("Kubernetes in production")
      .closest(".requirement-row") as HTMLElement;
    expect(within(unanswered).queryByText("Answered by you")).toBeNull();
  });

  it("asks for a custom section's heading before pricing it", async () => {
    const calls = serve((call) =>
      call.url.startsWith("/tailored-resumes/res-1/sections/estimate")
        ? { cost_usd: "0.02", model_id: "claude-opus-5" }
        : defaults(call),
    );
    const user = userEvent.setup();
    renderResume();

    await user.click(await screen.findByRole("button", { name: "+ Custom…" }));
    await user.type(
      screen.getByLabelText("Heading of your section"),
      "Volunteering",
    );
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(calls.find((c) => c.url.includes("/sections/estimate"))?.url).toBe(
      "/tailored-resumes/res-1/sections/estimate?kind=custom&title=Volunteering",
    );
  });
});

describe("the tool cards' summaries", () => {
  it("counts the requirements by verdict", () => {
    expect(
      coverageStatus([
        { verdict: "covered" },
        { verdict: "partial" },
        { verdict: "gap" },
      ]),
    ).toBe("1 covered · 1 partial · 1 gap");
    expect(coverageStatus([{ verdict: "gap" }, { verdict: "gap" }])).toBe(
      "0 covered · 0 partial · 2 gaps",
    );
    expect(coverageStatus([])).toBe("Once written");
  });

  it("names a saved résumé by its target, version and day, or what it is doing", () => {
    expect(savedLine(summary)).toBe(
      `${matched.label} · v1 · edited 20 Sep 2026`,
    );
    expect(savedLine({ ...summary, status: "drafting" })).toBe(
      `${matched.label} · writing…`,
    );
  });
});

describe("the undo stack", () => {
  it("keeps the newest fifty drafts", () => {
    let stack: ResumeContent[] = [];
    for (let i = 0; i < 55; i += 1) {
      stack = getStackWith(stack, { ...resume.content!, name: `Draft ${i}` });
    }
    expect(stack).toHaveLength(50);
    expect(stack[0]!.name).toBe("Draft 5");
    expect(stack[49]!.name).toBe("Draft 54");
  });
});
