import { useEffect } from "react";
import { api } from "../api/client";
import type {
  Fit,
  FitPage,
  MatchedPosting,
  MatchedPostingPage,
  PlanSummary,
  PlanSummaryPage,
  ResumeSummary,
  ResumeSummaryPage,
  Role,
  RolePage,
  TargetRef,
} from "../api/types";
import {
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
  StatTile,
} from "../components/ui";
import type { AdvisorTab, Focus } from "../shell/navigation";
import { useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { FillTheGap } from "./FillTheGap";
import { GapPlan } from "./GapPlan";
import { Resume } from "./Resume";
import { Credit, pickBand } from "./Roles";
import type { AdvisorTarget } from "./target";
import { useAsync } from "./useAsync";

/**
 * The Advisor: Fill the gap first, then either the gap plan or the tailored
 * résumé, for one Target (ADR 0023).
 *
 * The Target is what the role map selected — one role, and optionally one
 * opening in it (ADR 0022) — carried in the hash. There is no picker here:
 * "Change role" goes back to the role map, the only place a Target is chosen.
 */
export function Advisor({ tab }: { tab: AdvisorTab }) {
  const { focus, navigate } = useShell();
  const flash = useToast();
  const roles = useAsync<Role[]>(() => api.items<RolePage>("/roles"), []);
  const fits = useAsync<Fit[]>(() => api.items<FitPage>("/fits"), []);
  const openings = useAsync<MatchedPosting[]>(
    () =>
      focus
        ? api.items<MatchedPostingPage>(
            `/matched-postings?${new URLSearchParams({ role_id: focus.role })}`,
          )
        : Promise.resolve([]),
    [focus?.role],
  );
  const plans = useAsync<PlanSummary[]>(
    () => api.items<PlanSummaryPage>("/gap-plans"),
    [],
  );
  const resumes = useAsync<ResumeSummary[]>(
    () => api.items<ResumeSummaryPage>("/tailored-resumes"),
    [],
  );

  if (!focus) {
    return (
      <EmptyState title="Pick a role on the role map first">
        Select a role — or one of its openings — and press the target button at
        the bottom of the map. The Advisor then plans a route to it and writes
        your résumé for it.
        <span style={{ display: "block", marginTop: 14 }}>
          <Button onClick={() => navigate("roles")}>Open the role map</Button>
        </span>
      </EmptyState>
    );
  }

  const failed =
    roles.error ?? fits.error ?? openings.error ?? plans.error ?? resumes.error;
  if (failed) return <ErrorNote error={failed} />;
  if (
    !roles.data ||
    !fits.data ||
    !openings.data ||
    !plans.data ||
    !resumes.data
  ) {
    return <Loading what="the Advisor" />;
  }

  const target = targetFor(focus, roles.data, fits.data, openings.data);

  /** Reopen a plan or résumé kept for another Target. */
  function revisit(ref: TargetRef) {
    if (!(roles.data ?? []).some((role) => role.id === ref.role_id)) {
      flash(
        "That role is no longer on your map, so there is nothing to aim at.",
      );
      return;
    }
    navigate("advisor", { focus: focusOf(ref) });
  }

  if (!target) {
    return (
      <EmptyState title="That target is no longer on your role map">
        The role, or the opening in it, has left the map since you picked it.
        <span style={{ display: "block", marginTop: 14 }}>
          <Button onClick={() => navigate("roles")}>Change role</Button>
        </span>
      </EmptyState>
    );
  }

  return (
    <Aimed
      key={`${target.ref.role_id}:${target.ref.job_posting_id ?? ""}`}
      target={target}
      tab={tab}
      plans={plans.data}
      resumes={resumes.data}
      onPlansChanged={() => void plans.reload()}
      onResumesChanged={() => void resumes.reload()}
      onRevisit={revisit}
    />
  );
}

/** The Advisor for one Target. Remounted when the Target changes. */
function Aimed({
  target,
  tab,
  plans,
  resumes,
  onPlansChanged,
  onResumesChanged,
  onRevisit,
}: {
  target: AdvisorTarget;
  tab: AdvisorTab;
  plans: PlanSummary[];
  resumes: ResumeSummary[];
  onPlansChanged: () => void;
  onResumesChanged: () => void;
  onRevisit: (ref: TargetRef) => void;
}) {
  const { navigate, setTarget } = useShell();

  // The header's chip names the Target both tabs are aimed at.
  useEffect(() => {
    setTarget(
      `${target.label}${target.fit !== null ? ` · ${target.fit}%` : ""}`,
    );
    return () => setTarget(null);
  }, [target, setTarget]);

  return (
    <section>
      <TargetBanner target={target} onChange={() => navigate("roles")} />

      <div
        className="row advisor-steps"
        role="group"
        aria-label="Advisor tabs"
        style={{ marginBottom: 20, alignItems: "center" }}
      >
        <span className="eyebrow">First</span>
        <PillToggle
          pressed={tab === "gaps"}
          onClick={() => navigate("advisor", { tab: "gaps" })}
        >
          Fill the gap
        </PillToggle>
        <span className="muted" aria-hidden="true">
          →
        </span>
        <span className="eyebrow">Then, either</span>
        <PillToggle
          pressed={tab === "plan"}
          onClick={() => navigate("advisor", { tab: "plan" })}
        >
          Gap plan
        </PillToggle>
        <PillToggle
          pressed={tab === "resume"}
          onClick={() => navigate("advisor", { tab: "resume" })}
        >
          Résumé
        </PillToggle>
      </div>
      {tab === "gaps" ? (
        <FillTheGap
          target={target}
          onSubmitted={() => {
            onPlansChanged();
            onResumesChanged();
          }}
        />
      ) : tab === "plan" ? (
        <GapPlan
          target={target}
          history={plans}
          onChanged={onPlansChanged}
          onRevisit={(entry) => onRevisit(entry.target)}
        />
      ) : (
        <Resume
          target={target}
          saved={resumes}
          onChanged={onResumesChanged}
          onRevisit={(entry) => onRevisit(entry.target)}
        />
      )}
    </section>
  );
}

/** "Your target role": the one thing every number on this page is about. */
function TargetBanner({
  target,
  onChange,
}: {
  target: AdvisorTarget;
  onChange: () => void;
}) {
  const where = [target.company, target.location, target.postingTitle]
    .filter(Boolean)
    .join(" · ");
  return (
    <div
      className="panel panel-tight"
      role="region"
      aria-label="Your target role"
      style={{ marginBottom: 20 }}
    >
      <div
        className="row-between"
        style={{ alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}
      >
        <div style={{ minWidth: 0 }}>
          <Eyebrow>
            {target.isCustom ? "Your target role · yours" : "Your target role"}
          </Eyebrow>
          <div
            style={{
              fontFamily: "var(--font-heading)",
              fontSize: 22,
              marginTop: 4,
            }}
          >
            {target.roleName}
          </div>
          {where && (
            <div className="subcopy" style={{ margin: "2px 0 0" }}>
              at {where}
              {target.postingTitle ? " posting" : ""}
              <Credit to={target.creditedTo} url={target.url} />
            </div>
          )}
          <p className="muted" style={{ fontSize: 12.5, margin: "8px 0 0" }}>
            Everything on this page is measured against this one role.
          </p>
        </div>
        <div className="row" style={{ gap: 10, alignItems: "stretch" }}>
          <StatTile
            label="Fit today"
            value={target.fit !== null ? `${target.fit}%` : "—"}
          />
          <StatTile label="Band" value={target.band ?? "—"} />
          <Button variant="ghost" onClick={onChange}>
            Change role
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * The Target a focus names, from the role map's own data; null when the role,
 * or the opening in it, has left the map. Pure.
 */
export function targetFor(
  focus: Focus,
  roles: Role[],
  fits: Fit[],
  openings: MatchedPosting[],
): AdvisorTarget | null {
  const role = roles.find((r) => r.id === focus.role);
  if (!role) return null;
  const roleFit = fits.find((f) => f.role_id === role.id)?.score ?? null;
  const opening = focus.opening
    ? openings.find(
        (o) => o.posting_id === focus.opening && o.role_id === role.id,
      )
    : undefined;
  if (focus.opening && !opening) return null;

  const roleBand = pickBand(role.salary_bands);
  const company = opening?.company_name ?? role.company_name ?? null;
  return {
    ref: { role_id: role.id, job_posting_id: opening?.posting_id ?? null },
    label: company ? `${role.name} · ${company}` : role.name,
    roleName: role.name,
    company,
    location: opening?.location ?? null,
    postingTitle: opening?.title ?? null,
    url: opening?.url ?? null,
    creditedTo: opening?.credited_to ?? null,
    fit: opening?.fit ?? roleFit,
    band: opening?.salary
      ? money(opening.salary.currency, opening.salary.min, opening.salary.max)
      : roleBand
        ? money(roleBand.currency, roleBand.low, roleBand.high)
        : null,
    isCustom: role.origin === "custom",
  };
}

/** Where a Target sits on the role map. Pure. */
export function focusOf(ref: TargetRef): Focus {
  return ref.job_posting_id
    ? { role: ref.role_id, opening: ref.job_posting_id }
    : { role: ref.role_id };
}

function money(currency: string, low: number, high: number): string {
  return `${currency} ${Math.round(low / 1000)}k–${Math.round(high / 1000)}k`;
}
