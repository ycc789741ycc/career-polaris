import { useMemo, useState } from "react";
import { ApiError, api } from "../api/client";
import type {
  Assessment,
  Fit,
  FitPage,
  MatchedPosting,
  MatchedPostingPage,
  Role,
  RoleMapEstimate,
  RoleMapState,
  RolePage,
  SalaryBand,
  MarketScope,
  PlanEstimate,
  TargetRef,
} from "../api/types";
import { RoleMap, type RoleBubble } from "../charts/RoleMap";
import {
  AutoGrid,
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  SkillFitBar,
  StatTile,
} from "../components/ui";
import { useActivity } from "../shell/activity";
import { type Focus, roleFocus } from "../shell/navigation";
import { modelName, useHeading, useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { targetQuery } from "./target";
import {
  EmptyMap,
  getBuildSteps,
  isMapComing,
  RunProgress,
} from "./RunProgress";
import { dayLabel, postedLabel } from "./time";
import { messageOf, useAsync } from "./useAsync";

/**
 * The role map: which roles exist in this user's market, and how they fit.
 *
 * What is selected here — a role, or a JD the user pasted — is what the
 * Advisor aims at. The selection lives in the hash, so it survives a reload
 * and the trip to the Advisor and back.
 */
export function Roles() {
  const { navigate, focus: anyFocus, setFocus, status } = useShell();
  // A posting of your own is aimed at from the Advisor; the map selects roles.
  const focus = roleFocus(anyFocus);
  const { activity, refresh: refreshActivity, settled } = useActivity();
  // What a finished build or analysis wrote shows without a reload.
  const roles = useAsync<Role[]>(
    () => api.items<RolePage>("/roles"),
    [settled.roleMap],
  );
  const fits = useAsync<Fit[]>(
    () => api.items<FitPage>("/fits"),
    [settled.roleMap, settled.analysis],
  );
  const assessment = useAsync<Assessment | null>(
    () => api.get("/assessments/latest"),
    [settled.analysis],
  );
  const scope = useAsync<MarketScope>(() => api.get("/market-scope"), []);
  // How current the map is: it is built only when asked for (ADR 0027).
  const state = useAsync<RoleMapState>(
    () => api.get("/role-map"),
    [settled.roleMap],
  );

  // What a rebuild would cost, for the toolbar's line. Pricing calls no model.
  const rebuildCost = useAsync<RoleMapEstimate>(
    () => api.get("/roles/cost-estimate"),
    [settled.analysis, settled.roleMap],
  );
  const [estimate, setEstimate] = useState<RoleMapEstimate | null>(null);
  // "Target this role" prices writing its questions first (ADR 0042).
  const [questionCost, setQuestionCost] = useState<{
    focus: Focus;
    label: string;
    cost: PlanEstimate;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fitByRole = useMemo(
    () => new Map((fits.data ?? []).map((fit) => [fit.role_id, fit])),
    [fits.data],
  );
  const dimensionNames = useMemo(
    () =>
      new Map((assessment.data?.dimensions ?? []).map((d) => [d.key, d.name])),
    [assessment.data],
  );

  const bubbles: RoleBubble[] = (roles.data ?? []).map((role) => {
    const band = pickBand(role.salary_bands);
    const fit = fitByRole.get(role.id);
    return {
      id: role.id,
      name: role.name,
      hiringBar: role.hiring_bar,
      barBasis: role.bar_basis,
      salaryMid: band?.mid ?? null,
      salaryCurrency: band?.currency ?? null,
      salaryLabel: band ? bandLabel(band) : null,
      openings: role.opening_count,
      fit: fit?.score ?? null,
      reasoning: fit?.reasoning ?? role.bar_reasoning,
    };
  });

  // With nothing picked, the role that fits best is the one worth reading. A
  // picked role no longer on the map falls back to it too.
  const bestId = [...bubbles].sort((a, b) => (b.fit ?? -1) - (a.fit ?? -1))[0]
    ?.id;
  const pickedId = focus
    ? bubbles.find((b) => b.id === focus.role)?.id
    : undefined;
  const activeId = pickedId ?? bestId;
  const activeRole = (roles.data ?? []).find((role) => role.id === activeId);
  const activeFit = activeId ? fitByRole.get(activeId) : undefined;
  const activeBand = activeRole ? pickBand(activeRole.salary_bands) : null;
  // "Openings for this role": every posting in the selected role, newest
  // first, ten at a time (ADR 0049). The first ten show until "See all" pages
  // through the rest; picking another role starts again at its first page.
  const [paging, setPaging] = useState<{ roleId: string; page: number } | null>(
    null,
  );
  const isPaged = paging !== null && paging.roleId === activeId;
  const openingsPage = isPaged ? paging.page : 1;
  const openings = useAsync<MatchedPostingPage | null>(
    () =>
      activeId
        ? api.get<MatchedPostingPage>(
            `/matched-postings?${new URLSearchParams({
              role_id: activeId,
              one_per_company: "false",
              order: "newest",
              page: String(openingsPage),
              page_size: String(OPENINGS_PAGE_SIZE),
            })}`,
          )
        : Promise.resolve(null),
    [activeId, openingsPage, settled.roleMap, settled.analysis],
  );
  const openingsTotal = openings.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(openingsTotal / OPENINGS_PAGE_SIZE));

  // The one thing the Advisor will be aimed at (ADR 0022): the role shown as
  // selected, the best fit until the user picks one. An opening is aimed at
  // only from a target set before (ADR 0049): the map lists them, unranked.
  const aim: { focus: Focus; label: string; what: string } | null = activeRole
    ? {
        focus: { role: activeRole.id },
        label: activeRole.name,
        what: "role",
      }
    : null;

  const analysing = activity?.analysis?.status === "running";
  // While a build runs or is about to, its waiting screen is the page.
  const waiting = isMapComing(activity);
  useHeading(waiting ? "Building your role map" : null);

  /** Price the questions for what the bar aims at; a Target with nothing to
   * ask about, or one already being prepared, opens without a spend. */
  async function priceTarget(target: { focus: Focus; label: string }) {
    setBusy(true);
    setError(null);
    try {
      const cost = await api.get<PlanEstimate>(
        `/gap-question-sets/cost-estimate?${targetQuery(refOf(target.focus))}`,
      );
      setQuestionCost({ ...target, cost });
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "target_unusable") {
        navigate("advisor", { tab: "gaps", focus: target.focus });
      } else {
        setError(messageOf(caught));
      }
    } finally {
      setBusy(false);
    }
  }

  /** Aim the Advisor and start writing the questions: Fill the gap opens
   * preparing, and every other tab stays usable meanwhile. */
  async function targetAndAsk() {
    if (!questionCost) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/gap-question-sets", refOf(questionCost.focus));
    } catch (caught) {
      // Questions already being written for it: open them as they are.
      if (!(caught instanceof ApiError && caught.code === "conflict")) {
        setError(messageOf(caught));
        setBusy(false);
        return;
      }
    }
    setBusy(false);
    const focus = questionCost.focus;
    setQuestionCost(null);
    await refreshActivity();
    navigate("advisor", { tab: "gaps", focus });
  }

  async function rebuild() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/roles/recluster");
      setEstimate(null);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
      await refreshActivity();
    }
  }

  async function askForEstimate() {
    setBusy(true);
    setError(null);
    try {
      setEstimate(await api.get<RoleMapEstimate>("/roles/cost-estimate"));
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  if (waiting) {
    const model = modelName(status.credential);
    return (
      <RunProgress
        label="Role map progress"
        heading="Finding the roles that fit you best"
        subline={
          analysing
            ? "Starts automatically when your strength analysis finishes. Usually takes 2–4 minutes."
            : "Usually takes 2–4 minutes."
        }
        startedAt={
          activity?.role_map?.started_at ??
          activity?.analysis?.started_at ??
          null
        }
        steps={getBuildSteps({
          activity,
          assessment: assessment.data,
          scope: scope.data ? scopeLine(scope.data).replace(/\.$/, "") : null,
          maxRoles: rebuildCost.data?.max_roles ?? null,
        })}
        previewTitle="Your map will appear here"
        preview={<EmptyMap />}
        previewNote="It is drawn once the roles are picked and scored."
        leaveCopy="The search keeps running if you leave this page. The running bar says when your map is ready."
        back={{
          label: "Back to Strengths",
          onClick: () => navigate("strengths"),
        }}
        costCopy={`Charged to your own key on ${model}, at the estimate you confirmed before it started. Searching only ${
          scope.data && scope.data.target_locations.length > 0
            ? scope.data.target_locations.join(" and ")
            : "your locations"
        } keeps this down.`}
      />
    );
  }

  return (
    <section>
      <div
        className="row report-toolbar"
        style={{ gap: 14, flexWrap: "wrap", marginBottom: 18 }}
      >
        <Button variant="secondary" busy={busy} onClick={askForEstimate}>
          Rebuild role map
        </Button>
        <span style={{ fontSize: 13, color: "var(--color-neutral-800)" }}>
          {builtLine({
            builtAt:
              activity?.role_map?.status === "ready"
                ? activity.role_map.finished_at
                : (state.data?.market_data_at ?? null),
            model: modelName(status.credential),
            scope: scope.data ?? null,
            rebuildCostUsd: rebuildCost.data?.cost_usd ?? null,
          })}
        </span>
      </div>
      {state.data?.locations_changed && (
        <p
          role="status"
          className="note-warning"
          style={{ margin: "0 0 14px" }}
        >
          <span aria-hidden="true">⚠</span> Your locations changed since this
          map was built. Rebuild to search the new places.
        </p>
      )}
      <ErrorNote error={error} />
      {questionCost && (
        <CostConfirm
          busy={busy}
          onCancel={() => setQuestionCost(null)}
          onConfirm={() => void targetAndAsk()}
        >
          Aiming the Advisor at {questionCost.label} starts by writing your
          follow-up questions about its gaps. That costs about{" "}
          <strong>${questionCost.cost.cost_usd}</strong> on{" "}
          {questionCost.cost.model_id} and runs in the background — the gap plan
          and the résumé stay open while it does.
        </CostConfirm>
      )}
      {estimate && (
        <CostConfirm
          busy={busy}
          onCancel={() => setEstimate(null)}
          onConfirm={() => void rebuild()}
        >
          Your map covers up to {estimate.max_roles} of the roles your last
          analysis recommended. Naming them and scoring your fit against each
          will cost at most <strong>${estimate.cost_usd}</strong> on{" "}
          {estimate.model_id} — usually less, since your locations may have
          openings for fewer roles than that, and roles already analysed are not
          paid for again. Searching the postings runs on our machines; your key
          pays only for naming the roles, reading out what they require, and
          your fit.
        </CostConfirm>
      )}

      {roles.loading ? (
        <Loading what="your roles" />
      ) : bubbles.length === 0 ? (
        <EmptyState title="No roles yet">
          Choose where you want to work on Sources, then analyse your strengths:
          each analysis recommends the roles they point to, and the role map
          shows the ones with openings where you want to work.
        </EmptyState>
      ) : (
        <AutoGrid col={400} gap={20}>
          <div className="panel">
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ margin: 0 }}>Role market map</h3>
              <div className="subcopy">
                Bubble size = fit. The {bubbles.length} best-fit roles on the
                market in your locations.
              </div>
            </div>
            <RoleMap
              roles={bubbles}
              selectedId={activeId}
              onSelect={(id) => setFocus({ role: id })}
            />
          </div>

          {activeRole && (
            <div className="panel panel-column">
              <Eyebrow>Selected role</Eyebrow>
              <h3 style={{ fontSize: 27, margin: "8px 0 6px" }}>
                {activeRole.name}
              </h3>
              <AutoGrid col={110} gap={10} style={{ margin: "10px 0 16px" }}>
                <StatTile
                  label="Fit"
                  value={activeFit ? `${activeFit.score}%` : "—"}
                  note={`across ${postingCount(activeRole.opening_count)}`}
                />
                <StatTile
                  label="Annual pay"
                  value={
                    activeBand
                      ? payRange(
                          activeBand.currency,
                          activeBand.low,
                          activeBand.high,
                        )
                      : "—"
                  }
                  note={scope.data?.target_locations.join(" · ") || undefined}
                />
                <StatTile
                  label="Openings"
                  value={String(activeRole.opening_count)}
                  note="in your locations"
                />
              </AutoGrid>
              {activeFit && activeFit.gaps.length > 0 && (
                <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>
                  You clear {getClearCount(activeFit.gaps)} of{" "}
                  {activeFit.gaps.length} skills this role screens for.
                </div>
              )}
              <p style={{ fontSize: 14.5, lineHeight: 1.65, marginTop: 0 }}>
                {activeFit?.reasoning ??
                  activeRole.bar_reasoning ??
                  "Not scored yet — run an analysis, then rebuild the map."}
              </p>

              {activeFit && activeFit.gaps.length > 0 && (
                <>
                  <div className="row-between" style={{ marginTop: 6 }}>
                    <Eyebrow>How you fit each skill</Eyebrow>
                    <span className="muted" style={{ fontSize: 12 }}>
                      Biggest gap first
                    </span>
                  </div>
                  <SkillFitLegend />
                  <ul
                    style={{ listStyle: "none", margin: "4px 0 0", padding: 0 }}
                  >
                    {getSkillFits(activeFit.gaps, dimensionNames).map(
                      (skill) => (
                        <li
                          key={skill.key}
                          style={{
                            padding: "11px 0",
                            borderBottom:
                              "1px solid color-mix(in srgb, #201e1d 10%, transparent)",
                          }}
                        >
                          <div
                            className="row-between"
                            style={{ alignItems: "baseline", gap: 12 }}
                          >
                            <span style={{ fontSize: 14, fontWeight: 600 }}>
                              {skill.name}
                            </span>
                            <span
                              className="row"
                              style={{
                                gap: 10,
                                flex: "0 0 auto",
                                fontSize: 12.5,
                                color: "var(--color-neutral-800)",
                                alignItems: "baseline",
                              }}
                            >
                              <span>
                                you{" "}
                                <b style={{ color: "var(--color-text)" }}>
                                  {skill.you}
                                </b>{" "}
                                · asks{" "}
                                <b style={{ color: "var(--color-text)" }}>
                                  {skill.asks}
                                </b>
                              </span>
                              <span
                                className={
                                  skill.delta < 0
                                    ? "delta-chip delta-chip-short"
                                    : "delta-chip delta-chip-clear"
                                }
                              >
                                {signed(skill.delta)}
                              </span>
                            </span>
                          </div>
                          <SkillFitBar
                            you={skill.you}
                            asks={skill.asks}
                            label={skill.name}
                          />
                        </li>
                      ),
                    )}
                  </ul>
                </>
              )}

              <details style={{ marginTop: 16 }}>
                <summary
                  className="eyebrow"
                  style={{ cursor: "pointer", display: "list-item" }}
                >
                  What this role asks for
                </summary>
                <ul
                  style={{ fontSize: 13.5, margin: "8px 0 0", paddingLeft: 18 }}
                >
                  {activeRole.requirements.map((requirement) => (
                    <li key={requirement.statement}>
                      {requirement.statement}{" "}
                      <span className="muted">
                        ({requirement.expected_level})
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </AutoGrid>
      )}

      {activeRole && (openings.data?.items ?? []).length > 0 && (
        <div className="panel" style={{ marginTop: 20 }}>
          <h3>Openings for this role</h3>
          <p className="subcopy">
            {openingsLine(
              openingsTotal,
              activeRole.name,
              scope.data?.target_locations ?? [],
            )}
          </p>
          <ul className="openings-list" aria-label="Openings for this role">
            {(openings.data?.items ?? []).map((match) => (
              <OpeningRow key={match.posting_id} match={match} />
            ))}
          </ul>
          {isPaged ? (
            <nav
              className="row"
              aria-label="Openings pages"
              style={{ gap: 10, marginTop: 12, alignItems: "center" }}
            >
              <Button
                variant="secondary"
                disabled={openingsPage <= 1}
                onClick={() =>
                  setPaging({ roleId: activeRole.id, page: openingsPage - 1 })
                }
              >
                Previous
              </Button>
              <span className="subcopy" style={{ margin: 0 }}>
                Page {openingsPage} of {pageCount}
              </span>
              <Button
                variant="secondary"
                disabled={openingsPage >= pageCount}
                onClick={() =>
                  setPaging({ roleId: activeRole.id, page: openingsPage + 1 })
                }
              >
                Next
              </Button>
            </nav>
          ) : (
            openingsTotal > OPENINGS_PAGE_SIZE && (
              <button
                type="button"
                className="link-button"
                style={{ marginTop: 10 }}
                onClick={() => setPaging({ roleId: activeRole.id, page: 1 })}
              >
                See all {openingsTotal} openings
              </button>
            )
          )}
        </div>
      )}

      {aim && (
        <div
          className="panel panel-tight target-bar"
          role="region"
          aria-label="Advisor target"
        >
          <div style={{ minWidth: 0 }}>
            <Eyebrow>Advisor target</Eyebrow>
            <div className="ellipsis target-bar-label">{aim.label}</div>
          </div>
          <Button busy={busy} onClick={() => void priceTarget(aim)}>
            Target this {aim.what}
          </Button>
        </div>
      )}
    </section>
  );
}

/** One opening: its company, then the posting, where and what it pays, and
 * how long ago it was posted. No fit: it is the role's (ADR 0049). */
function OpeningRow({ match }: { match: MatchedPosting }) {
  return (
    <li className="opening-row">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>
          {match.company_name}
        </div>
        <div className="subcopy" style={{ fontSize: 12.5, marginTop: 2 }}>
          {match.url ? (
            <a href={match.url} rel="noreferrer" target="_blank">
              {match.title}
            </a>
          ) : (
            match.title
          )}
          {[
            match.location,
            match.salary
              ? annualPay(
                  match.salary.currency,
                  match.salary.min,
                  match.salary.max,
                )
              : null,
          ]
            .filter(Boolean)
            .map((part) => ` · ${part}`)
            .join("")}
          <Credit to={match.credited_to} url={match.url} />
        </div>
      </div>
      {match.posted_on && (
        <span className="subcopy" style={{ flex: "0 0 auto", fontSize: 12 }}>
          {postedLabel(match.posted_on)}
        </span>
      )}
    </li>
  );
}

const OPENINGS_PAGE_SIZE = 10;

/** "38 open postings for Staff Backend Engineer in Berlin and Remote EU,
 * newest first. …" Pure. */
export function openingsLine(
  total: number,
  roleName: string,
  places: readonly string[],
): string {
  const count = `${total.toLocaleString("en")} open ${
    total === 1 ? "posting" : "postings"
  } for ${roleName}`;
  const where = places.length > 0 ? ` in ${listed(places)}` : "";
  return `${count}${where}, newest first. Your fit is scored on the role, so it is the same for every opening.`;
}

/** "Berlin", "Berlin and Remote EU", "A, B and C". Pure. */
function listed(places: readonly string[]): string {
  return places.length === 1
    ? places[0]!
    : `${places.slice(0, -1).join(", ")} and ${places[places.length - 1]}`;
}

/** "1,284 open postings in Berlin and Remote EU". Pure. */
export function scopeLine(scope: MarketScope): string {
  const count = `${scope.open_posting_count.toLocaleString("en")} open ${
    scope.open_posting_count === 1 ? "posting" : "postings"
  }`;
  const places = scope.target_locations;
  if (places.length === 0) return `${count} in the platform's baseline.`;
  return `${count} in ${listed(places)}.`;
}

/**
 * The band for one market, or the best-sampled one. A thin band is still
 * shown, just flagged. Pure.
 */
export function pickBand(
  bands: Record<string, SalaryBand>,
  market: string | null = null,
): SalaryBand | null {
  if (market !== null) return bands?.[market] ?? null;
  const entries = Object.values(bands ?? {});
  if (entries.length === 0) return null;
  return entries.find((band) => band.is_confident) ?? entries[0] ?? null;
}

/**
 * A pay range with its currency code, in thousands: "EUR 80k–105k". Every
 * amount the market stores is yearly — the crawlers drop hourly and monthly
 * rates — so the range is always a year's pay. Pure.
 */
export function payRange(currency: string, low: number, high: number): string {
  return `${currency} ${Math.round(low / 1000)}k–${Math.round(high / 1000)}k`;
}

/** {@link payRange}, saying that it is a year's pay. Pure. */
export function annualPay(currency: string, low: number, high: number): string {
  return `${payRange(currency, low, high)} a year`;
}

function bandLabel(band: SalaryBand): string {
  return `${annualPay(band.currency, band.low, band.high)}${band.is_confident ? "" : " (thin sample)"}`;
}

/**
 * Names the job site an opening was found through, linked to the opening
 * there: that site's terms ask for both wherever the opening is shown
 * (ADR 0025). Nothing for an opening from the employer's own board.
 */
export function Credit({
  to,
  url,
}: {
  to: string | null | undefined;
  url: string | null;
}) {
  if (!to) return null;
  return (
    <>
      {" · via "}
      {url ? (
        <a href={url} rel="noreferrer" target="_blank">
          {to}
        </a>
      ) : (
        to
      )}
    </>
  );
}

/** "38 postings". Pure. */
function postingCount(count: number): string {
  return `${count.toLocaleString("en")} ${count === 1 ? "posting" : "postings"}`;
}

/**
 * The role map toolbar's line, laid out as Strengths' is: "Built 26 Sep 2026
 * on claude-sonnet-5 · 1,284 open postings in Berlin and Remote EU · about
 * $0.40 on your key to rebuild". Each part is left out until it is known. Pure.
 */
export function builtLine({
  builtAt,
  model,
  scope,
  rebuildCostUsd,
}: {
  builtAt: string | null;
  model: string;
  scope: MarketScope | null;
  rebuildCostUsd: string | null;
}): string {
  const parts: string[] = [];
  parts.push(
    builtAt ? `Built ${dayLabel(builtAt)} on ${model}` : "Not built yet",
  );
  if (scope) parts.push(scopeLine(scope).replace(/\.$/, ""));
  if (rebuildCostUsd !== null) {
    parts.push(`about $${rebuildCostUsd} on your key to rebuild`);
  }
  return parts.join(" · ");
}

/** How many of a fit's skills the user already meets. Pure. */
export function getClearCount(
  gaps: readonly { user_score: number; target_score: number }[],
): number {
  return gaps.filter((gap) => gap.user_score >= gap.target_score).length;
}

export interface SkillFit {
  key: string;
  name: string;
  you: number;
  asks: number;
  /** You minus what the role asks: negative is a shortfall. */
  delta: number;
}

/**
 * A fit's skills as the selected-role card lists them: by display name, never
 * the dimension's key, biggest gap first. Pure.
 */
export function getSkillFits(
  gaps: readonly {
    dimension_key: string;
    user_score: number;
    target_score: number;
  }[],
  names: ReadonlyMap<string, string>,
): SkillFit[] {
  return gaps
    .map((gap) => ({
      key: gap.dimension_key,
      name: names.get(gap.dimension_key) ?? humanizeKey(gap.dimension_key),
      you: gap.user_score,
      asks: gap.target_score,
      delta: gap.user_score - gap.target_score,
    }))
    .sort((a, b) => a.delta - b.delta || a.name.localeCompare(b.name));
}

/** "backend-eng-python" → "Backend eng python", for a key with no name. Pure. */
export function humanizeKey(key: string): string {
  const words = key.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "−23" or "+14", with a real minus sign. Pure. */
export function signed(delta: number): string {
  return delta < 0 ? `\u2212${Math.abs(delta)}` : `+${delta}`;
}

function SkillFitLegend() {
  return (
    <div className="skill-fit-legend" aria-hidden="true">
      <span>
        <span className="legend-swatch legend-short" />
        You, below the bar
      </span>
      <span>
        <span className="legend-swatch legend-clear" />
        You, clear it
      </span>
      <span>
        <span className="legend-swatch legend-shortfall" />
        Shortfall
      </span>
      <span>
        <span className="legend-swatch legend-target" />
        What the role asks
      </span>
    </div>
  );
}

/** The Target a role-map focus names. Pure. */
function refOf(focus: Focus): TargetRef {
  if ("posting" in focus)
    return { role_id: null, private_job_posting_id: focus.posting };
  return { role_id: focus.role, job_posting_id: focus.opening ?? null };
}
