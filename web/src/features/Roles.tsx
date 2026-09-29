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
  RoleMapSettings,
  RolePage,
  SalaryBand,
  MarketScope,
  TargetOption,
  TargetOptionPage,
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
import { OwnJdPanel } from "./OwnJd";
import { messageOf, useAsync } from "./useAsync";

// The bound the api enforces on k (ADR 0003). The api is the authority; these
// only keep the input from offering a value it would refuse.
const MIN_ROLE_COUNT = 3;
const MAX_ROLE_COUNT = 20;

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
  const settings = useAsync<RoleMapSettings>(
    () => api.get("/roles/settings"),
    [],
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
  // For the pasted JDs: the only Targets that are not a role on the map.
  const targets = useAsync<TargetOption[]>(
    () => api.items<TargetOptionPage>("/targets"),
    [],
  );
  const matched = useAsync<MatchedPosting[]>(
    () => api.items<MatchedPostingPage>("/matched-postings?page_size=10"),
    [settled.roleMap, settled.analysis],
  );

  const [estimate, setEstimate] = useState<RoleMapEstimate | null>(null);
  // The k being considered; saved only once its estimate is confirmed.
  const [roleCount, setRoleCount] = useState<number | null>(null);
  const savedRoleCount = settings.data?.role_count;
  const chosenRoleCount = roleCount ?? savedRoleCount;
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
    };
  });

  // With nothing picked, the role that fits best is the one worth reading. A
  // picked role no longer on the map falls back to it too; a picked JD means
  // no role is selected.
  const bestId = [...bubbles].sort((a, b) => (b.fit ?? -1) - (a.fit ?? -1))[0]
    ?.id;
  const pickedId =
    focus?.kind === "role" && bubbles.some((b) => b.id === focus.id)
      ? focus.id
      : undefined;
  const activeId = pickedId ?? (focus?.kind === "jd" ? undefined : bestId);
  const activeRole = (roles.data ?? []).find((role) => role.id === activeId);
  const activeFit = activeId ? fitByRole.get(activeId) : undefined;
  const activeBand = activeRole ? pickBand(activeRole.salary_bands) : null;

  const pastedJds = (targets.data ?? []).filter(
    (o) => o.kind === "privatePosting",
  );
  const pickedJd =
    focus?.kind === "jd" ? pastedJds.find((o) => o.id === focus.id) : undefined;
  // The one thing the Advisor will be aimed at: the picked JD, or the role
  // shown as selected — which is the best fit until the user picks one.
  const aim: { focus: Focus; label: string; what: string } | null = pickedJd
    ? {
        focus: { kind: "jd", id: pickedJd.id },
        label: pickedJd.label,
        what: "JD",
      }
    : activeRole
      ? {
          focus: { kind: "role", id: activeRole.id },
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
      setEstimate(
        await api.get<RoleMapEstimate>(
          chosenRoleCount === undefined
            ? "/roles/cost-estimate"
            : `/roles/cost-estimate?role_count=${chosenRoleCount}`,
        ),
      );
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
                if (
                  chosenRoleCount !== undefined &&
                  chosenRoleCount !== savedRoleCount
                ) {
                  // Saving a new k queues the rebuild itself.
                  await api.put("/roles/settings", {
                    role_count: chosenRoleCount,
                  });
                  await settings.reload();
                  setRoleCount(null);
                } else {
                  await api.post("/roles/recluster");
                }
                setEstimate(null);
              },
            )
          }
        >
          Your map covers up to {estimate.max_clusters ?? 0} of the{" "}
          {estimate.role_count ?? chosenRoleCount} roles closest to your
          profile. Naming them will cost at most{" "}
          <strong>${estimate.cost_usd}</strong> on {estimate.model_id} — usually
          less, since postings may form fewer roles than that, and roles already
          analysed are not paid for again. Grouping itself runs on our machines;
          your key pays only for naming the roles and reading out what they
          require.
        </CostConfirm>
      )}

      {roles.loading ? (
        <Loading what="your roles" />
      ) : bubbles.length === 0 ? (
        <EmptyState title="No roles yet">
          Choose where you want to work on Sources, then build your role map.
        </EmptyState>
      ) : (
        <AutoGrid col={400} gap={20}>
          <div className="panel">
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ margin: 0 }}>Role market map</h3>
              <div className="subcopy">
                Bubble size = fit.
                {scope.data && ` ${scopeLine(scope.data)}`}
              </div>
            </div>
            <RoleMap
              roles={bubbles}
              selectedId={activeId}
              onSelect={(id) => setFocus({ kind: "role", id })}
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
          <h3>Top matched openings</h3>
          <p className="subcopy">
            Open postings inside your roles, ranked by how well you fit the
            role. A posting&apos;s own requirements do not change its rank yet.
          </p>
          <div className="stack" style={{ gap: 8, marginTop: 12 }}>
            {(matched.data ?? []).map((match, index) => (
              <div
                key={match.posting_id}
                className="row"
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
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <OwnJdPanel
        pasted={pastedJds}
        selectedId={focus?.kind === "jd" ? focus.id : null}
        error={targets.error}
        onSelect={(id) => setFocus({ kind: "jd", id })}
        onAdded={async (id) => {
          await targets.reload();
          setFocus({ kind: "jd", id });
        }}
      />

      <AutoGrid col={300} gap={20} style={{ marginTop: 20 }}>
        <div className="panel">
          <h3>Roles to analyse</h3>
          <p className="subcopy">
            How many of the roles closest to your profile the map analyses —
            each one costs calls on your key.
          </p>
          <label className="field-label" htmlFor="role-count-input">
            Roles ({MIN_ROLE_COUNT}–{MAX_ROLE_COUNT})
          </label>
          <input
            id="role-count-input"
            className="input"
            type="number"
            min={MIN_ROLE_COUNT}
            max={MAX_ROLE_COUNT}
            style={{ maxWidth: 140 }}
            value={chosenRoleCount ?? ""}
            onChange={(event) => {
              setRoleCount(Number(event.target.value));
              setEstimate(null);
            }}
          />
          <div className="row" style={{ marginTop: 14 }}>
            <Button busy={busy} disabled={building} onClick={askForEstimate}>
              {activity?.role_map?.status === "waiting"
                ? "Waiting for analysis…"
                : building
                  ? "Building…"
                  : "Build role map"}
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
