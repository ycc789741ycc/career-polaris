import { useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  Assessment,
  Fit,
  FitPage,
  MatchedPosting,
  MatchedPostingPage,
  Role,
  RoleCandidate,
  RoleCandidatePage,
  RoleMapEstimate,
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
import type { Focus } from "../shell/navigation";
import { useShell } from "../shell/ShellContext";
import { CostConfirm } from "./CostConfirm";
import { CustomRoleForm } from "./CustomRole";
import { messageOf, useAsync } from "./useAsync";

/**
 * The role map: which roles exist in this user's market, and how they fit.
 *
 * What is selected here — a role, or a JD the user pasted — is what the
 * Advisor aims at. The selection lives in the hash, so it survives a reload
 * and the trip to the Advisor and back.
 */
export function Roles() {
  const { navigate, focus, setFocus } = useShell();
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
  const candidates = useAsync<RoleCandidate[]>(
    () => api.items<RoleCandidatePage>("/role-candidates"),
    [settled.roleMap, settled.analysis],
  );
  const scope = useAsync<MarketScope>(() => api.get("/market-scope"), []);
  const matched = useAsync<MatchedPosting[]>(
    () => api.items<MatchedPostingPage>("/matched-postings?page_size=10"),
    [settled.roleMap, settled.analysis],
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
      salaryLabel: band ? bandLabel(band) : null,
      openings: role.opening_count,
      fit: fit?.score ?? null,
      reasoning: fit?.reasoning ?? role.bar_reasoning,
      isCustom: role.origin === "custom",
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
          label: activeRole.company_name
            ? `${activeRole.name} · ${activeRole.company_name}`
            : activeRole.name,
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
              <Eyebrow>
                {activeRole.origin === "custom"
                  ? "Selected role · yours"
                  : "Selected role"}
              </Eyebrow>
              <h3 style={{ fontSize: 27, margin: "8px 0 6px" }}>
                {activeRole.name}
                {activeRole.company_name && (
                  <span className="muted" style={{ fontSize: 17 }}>
                    {" "}
                    · {activeRole.company_name}
                  </span>
                )}
              </h3>
              <AutoGrid col={110} gap={10} style={{ margin: "10px 0 16px" }}>
                <StatTile
                  label="Fit"
                  value={activeFit ? `${activeFit.score}%` : "—"}
                />
                <StatTile
                  label="Band"
                  value={activeBand ? bandShort(activeBand) : "—"}
                />
                <StatTile
                  label="Openings"
                  value={String(activeRole.opening_count)}
                />
              </AutoGrid>
              <p style={{ fontSize: 14.5, lineHeight: 1.65 }}>
                {activeFit?.reasoning ??
                  activeRole.bar_reasoning ??
                  (activeRole.origin === "custom"
                    ? "Not placed yet — it is read at the next build."
                    : "Not scored yet — run an analysis, then re-score fit.")}
              </p>
              {activeRole.origin === "custom" && (
                <div style={{ marginBottom: 12 }}>
                  <Button
                    variant="ghost"
                    busy={busy}
                    onClick={() =>
                      void act("Role removed from your map", async () => {
                        await api.del(`/roles/custom/${activeRole.id}`);
                        setFocus(null);
                        await roles.reload();
                      })
                    }
                  >
                    Remove from my map
                  </Button>
                </div>
              )}

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
          <h3>Top matched openings</h3>
          <p className="subcopy">
            Open postings inside your roles, ranked by how well you fit the
            role. Pick one to aim the Advisor at that opening; its own
            requirements do not change its rank yet.
          </p>
          <div className="stack" style={{ gap: 8, marginTop: 12 }}>
            {(matched.data ?? []).map((match, index) => (
              <div
                key={match.posting_id}
                className="row opening-row"
                role="button"
                tabIndex={0}
                aria-pressed={pickedOpening?.posting_id === match.posting_id}
                aria-label={`${match.role_name} · ${match.company_name}: ${match.title}`}
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
                    {match.role_name} · {match.company_name}
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
                    {match.salary
                      ? `${match.salary.currency} ${Math.round(match.salary.min / 1000)}k–${Math.round(match.salary.max / 1000)}k · `
                      : ""}
                    {match.url ? (
                      <a href={match.url} rel="noreferrer" target="_blank">
                        {match.title}
                      </a>
                    ) : (
                      match.title
                    )}
                    {match.location ? ` · ${match.location}` : ""}
                    <Credit to={match.credited_to} url={match.url} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <UnplacedCandidates
        candidates={candidates.data ?? []}
        onSources={() => navigate("sources")}
      />

      <CustomRoleForm
        onAdded={async (role) => {
          await Promise.all([roles.reload(), refreshActivity()]);
          setFocus({ role: role.id });
        }}
      />

      <AutoGrid col={300} gap={20} style={{ marginTop: 20 }}>
        <div className="panel">
          <h3>Keep your map current</h3>
          <p className="subcopy">
            The map is rebuilt after every analysis, and when the market in your
            locations changes. Rebuild it now, or re-score your fit against the
            roles already on it.
          </p>
          <div className="row" style={{ marginTop: 14 }}>
            <Button busy={busy} disabled={building} onClick={askForEstimate}>
              {activity?.role_map?.status === "waiting"
                ? "Waiting for analysis…"
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

function bandShort(band: SalaryBand): string {
  return `${Math.round(band.low / 1000)}–${Math.round(band.high / 1000)}k`;
}

function bandLabel(band: SalaryBand): string {
  return `${band.currency} ${bandShort(band)}${band.is_confident ? "" : " (thin sample)"}`;
}

/**
 * The roles the analysis recommended that are not on the map: the user's
 * target locations have too few openings for them (ADR 0024). Naming them says
 * why the map is short, and what to do about it.
 */
function UnplacedCandidates({
  candidates,
  onSources,
}: {
  candidates: RoleCandidate[];
  onSources: () => void;
}) {
  const unplaced = candidates.filter((c) => c.role_id === null);
  if (unplaced.length === 0) return null;
  return (
    <div className="panel" style={{ marginTop: 20 }}>
      <h3>From your strengths, not on your market yet</h3>
      <p className="subcopy">
        Your analysis also points to these roles, but your locations have too
        few openings for them right now. Add one as a role of your own below, or
        widen{" "}
        <button type="button" className="link-button" onClick={onSources}>
          where you want to work
        </button>
        .
      </p>
      <ul aria-label="Recommended roles without openings">
        {unplaced.map((candidate) => (
          <li key={candidate.id}>
            <strong>{candidate.title}</strong> — {candidate.description}
          </li>
        ))}
      </ul>
    </div>
  );
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
