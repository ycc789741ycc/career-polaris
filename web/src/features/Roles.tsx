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
  StatTile,
} from "../components/ui";
import { isBusy, useActivity } from "../shell/activity";
import { type Focus, roleFocus } from "../shell/navigation";
import { useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { messageOf, useAsync } from "./useAsync";

/**
 * The role map: which roles exist in this user's market, and how they fit.
 *
 * What is selected here — a role, or a JD the user pasted — is what the
 * Advisor aims at. The selection lives in the hash, so it survives a reload
 * and the trip to the Advisor and back.
 */
export function Roles() {
  const { navigate, focus: anyFocus, setFocus } = useShell();
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

  const [estimate, setEstimate] = useState<RoleMapEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<string | null>(null);

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

  return (
    <section>
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
                Bubble size = fit. The 10 best-fit roles on the market, built
                after your strength analysis.
                {scope.data && ` ${scopeLine(scope.data)}`}
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
                />
                <StatTile
                  label="Openings"
                  value={String(activeRole.opening_count)}
                />
              </AutoGrid>
              <p style={{ fontSize: 14.5, lineHeight: 1.65 }}>
                {activeFit?.reasoning ??
                  activeRole.bar_reasoning ??
                  "Not scored yet — run an analysis, then re-score fit."}
              </p>

              {activeFit && activeFit.gaps.length > 0 && (
                <>
                  <Eyebrow style={{ margin: "6px 0" }}>
                    Where you clear it / where you don&apos;t
                  </Eyebrow>
                  {[...activeFit.gaps]
                    .sort((a, b) => a.delta - b.delta)
                    .map((gap) => {
                      const color =
                        gap.delta >= 0
                          ? "var(--color-accent-2-700)"
                          : "var(--color-accent-700)";
                      return (
                        <div
                          key={gap.dimension_key}
                          className="row"
                          style={{
                            gap: 11,
                            flexWrap: "nowrap",
                            padding: "8px 0",
                            borderBottom:
                              "1px solid color-mix(in srgb, #201e1d 10%, transparent)",
                          }}
                        >
                          <span
                            className="dot"
                            style={{ background: color }}
                            aria-hidden="true"
                          />
                          <span style={{ fontSize: 13.5, flex: 1 }}>
                            {dimensionNames.get(gap.dimension_key) ??
                              gap.dimension_key}
                          </span>
                          <span
                            style={{ fontSize: 12.5, fontWeight: 700, color }}
                          >
                            {gap.delta >= 0 ? `+${gap.delta}` : gap.delta}
                          </span>
                        </div>
                      );
                    })}
                </>
              )}

              {activeFit && activeFit.uncovered.length > 0 && (
                <>
                  <Eyebrow style={{ margin: "16px 0 6px" }}>
                    No evidence at all for these
                  </Eyebrow>
                  <p className="subcopy" style={{ marginBottom: 6 }}>
                    Different from a low score: nothing in your profile speaks
                    to them either way.
                  </p>
                  <ul style={{ fontSize: 13.5, margin: 0, paddingLeft: 18 }}>
                    {activeFit.uncovered.map((item) => (
                      <li key={item.statement}>{item.statement}</li>
                    ))}
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

      <AutoGrid col={300} gap={20} style={{ marginTop: 20 }}>
        <div className="panel">
          <h3>Keep your map current</h3>
          <p className="subcopy">
            The map is built only when you ask: after an analysis, or a rebuild.
            Each build searches the market for your recommended roles first,
            reusing what was fetched recently. Rebuild it now, or re-score your
            fit against the roles already on it.
          </p>
          {state.data?.market_data_at && (
            <p className="muted" style={{ fontSize: 12.5, margin: "6px 0 0" }}>
              Market data as of{" "}
              {new Date(state.data.market_data_at).toLocaleDateString()}.
            </p>
          )}
          {state.data?.locations_changed && (
            <p className="chip chip-warn" style={{ margin: "10px 0 0" }}>
              Your locations changed since this map was built. Rebuild to search
              the new places.
            </p>
          )}
          <div className="row" style={{ marginTop: 14 }}>
            <Button busy={busy} disabled={building} onClick={askForEstimate}>
              {activity?.role_map?.status === "waiting"
                ? activity.role_map.waiting_for === "market"
                  ? "Searching the market…"
                  : "Waiting for analysis…"
                : building
                  ? "Building…"
                  : "Rebuild role map"}
            </Button>
            <Button
              variant="secondary"
              busy={busy}
              onClick={() =>
                act("Fits queued", () => api.post("/fits/compute"))
              }
            >
              Re-score fit
            </Button>
          </div>
        </div>
      </AutoGrid>

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
