import { useMemo, useState } from "react";
import { api } from "../api/client";
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
} from "../api/types";
import { RoleMap, type RoleBubble } from "../charts/RoleMap";
import {
  AutoGrid,
  Button,
  Done,
  EmptyState,
  ErrorNote,
  Eyebrow,
  FitBadge,
  Loading,
  SkillFitBar,
  StatTile,
} from "../components/ui";
import { isBusy, useActivity } from "../shell/activity";
import { type Focus, roleFocus } from "../shell/navigation";
import { modelName, useHeading, useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import {
  EmptyMap,
  getBuildSteps,
  isMapComing,
  RunProgress,
} from "./RunProgress";
import { dayLabel } from "./time";
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<string | null>(null);
  // While a build runs, the last map can still be read on request.
  const [showPrevious, setShowPrevious] = useState(false);

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
  // The selected role's best openings, each ranked by its own fit (Phase 8),
  // one per company; picking another role reloads them.
  const matched = useAsync<MatchedPosting[]>(
    () =>
      activeId
        ? api.items<MatchedPostingPage>(
            `/matched-postings?${new URLSearchParams({
              role_id: activeId,
              one_per_company: "true",
              page_size: "10",
            })}`,
          )
        : Promise.resolve([]),
    [activeId, settled.roleMap, settled.analysis],
  );
  // An opening picked in "Top matched openings", while its role is selected.
  const pickedOpening =
    pickedId && focus?.opening
      ? (matched.data ?? []).find(
          (m) => m.posting_id === focus.opening && m.role_id === pickedId,
        )
      : undefined;

  // The one thing the Advisor will be aimed at (ADR 0022): the role shown as
  // selected — the best fit until the user picks one — and the opening in it,
  // if one is picked.
  const aim: { focus: Focus; label: string; what: string } | null = activeRole
    ? pickedOpening
      ? {
          focus: { role: activeRole.id, opening: pickedOpening.posting_id },
          label: `${activeRole.name} · ${pickedOpening.company_name}`,
          what: "opening",
        }
      : {
          focus: { role: activeRole.id },
          label: activeRole.name,
          what: "role",
        }
    : null;

  const building = isBusy(activity?.role_map);
  const analysing = activity?.analysis?.status === "running";
  const waiting = isMapComing(activity) && !showPrevious;
  useHeading(waiting ? "Building your role map" : null);

  async function act(label: string, run: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await run();
      setQueued(label);
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
        previous={
          bubbles.length > 0
            ? {
                label: "See your last map",
                onClick: () => setShowPrevious(true),
              }
            : undefined
        }
      />
    );
  }

  return (
    <section>
      <div
        className="row report-toolbar"
        style={{ gap: 14, flexWrap: "wrap", marginBottom: 18 }}
      >
        <Button
          variant="secondary"
          busy={busy}
          disabled={building}
          onClick={askForEstimate}
        >
          {activity?.role_map?.status === "waiting"
            ? activity.role_map.waiting_for === "market"
              ? "Searching the market…"
              : "Waiting for analysis…"
            : building
              ? "Building…"
              : "Rebuild role map"}
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
      {queued && <Done>{queued}.</Done>}
      {estimate && (
        <CostConfirm
          busy={busy}
          onCancel={() => setEstimate(null)}
          onConfirm={() =>
            act(
              // A build asked for during an analysis waits for it (ADR 0018).
              analysing
                ? "Role map queued — it starts when your analysis finishes"
                : "Role map queued",
              async () => {
                await api.post("/roles/recluster");
                setEstimate(null);
              },
            )
          }
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

      {(matched.data ?? []).length > 0 && (
        <div className="panel" style={{ marginTop: 20 }}>
          <h3>
            Top matched openings{activeRole ? ` in ${activeRole.name}` : ""}
          </h3>
          <p className="subcopy">
            The selected role&apos;s open postings, the best one from each
            company, ranked by how well you fit each opening: the role&apos;s
            requirements, weighed by how much that opening asks for each. Pick
            one to aim the Advisor at it.
          </p>
          <div className="stack" style={{ gap: 8, marginTop: 12 }}>
            {(matched.data ?? []).map((match, index) => (
              <div
                key={`${match.role_id}:${match.posting_id}`}
                className="row opening-row"
                role="button"
                tabIndex={0}
                aria-pressed={pickedOpening?.posting_id === match.posting_id}
                aria-label={`${match.title} · ${match.company_name}`}
                onClick={() =>
                  setFocus({ role: match.role_id, opening: match.posting_id })
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setFocus({
                      role: match.role_id,
                      opening: match.posting_id,
                    });
                  }
                }}
                style={{
                  gap: 14,
                  flexWrap: "nowrap",
                  padding: "11px 14px",
                  borderRadius: 999,
                  background: "var(--color-bg)",
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--font-heading)",
                    fontSize: 13,
                    width: 26,
                    color: "var(--color-neutral-700)",
                  }}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <FitBadge fit={match.fit} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 700,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {match.url ? (
                      <a href={match.url} rel="noreferrer" target="_blank">
                        {match.title}
                      </a>
                    ) : (
                      match.title
                    )}{" "}
                    · {match.company_name}
                  </div>
                  <div
                    className="subcopy"
                    style={{
                      fontSize: 12.5,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {[
                      match.salary
                        ? annualPay(
                            match.salary.currency,
                            match.salary.min,
                            match.salary.max,
                          )
                        : null,
                      match.location,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    <Credit to={match.credited_to} url={match.url} />
                  </div>
                </div>
              </div>
            ))}
          </div>
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
          <Button onClick={() => navigate("advisor", { focus: aim.focus })}>
            Target this {aim.what}
          </Button>
        </div>
      )}
    </section>
  );
}

/** "1,284 open postings in Berlin and Remote EU". Pure. */
export function scopeLine(scope: MarketScope): string {
  const count = `${scope.open_posting_count.toLocaleString("en")} open ${
    scope.open_posting_count === 1 ? "posting" : "postings"
  }`;
  const places = scope.target_locations;
  if (places.length === 0) return `${count} in the platform's baseline.`;
  const named =
    places.length === 1
      ? places[0]
      : `${places.slice(0, -1).join(", ")} and ${places[places.length - 1]}`;
  return `${count} in ${named}.`;
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
