import { useEffect, useMemo, useState } from "react";
import { useActivity } from "../shell/activity";
import {
  AdvisorJobCard,
  AdvisorJobNotice,
  jobsFor,
  jobTab,
} from "./AdvisorJobs";
import {
  AdvisorSteps,
  FillGapBanner,
  FillGapFirst,
  getGapFillState,
  getStepNotes,
} from "./AdvisorSteps";
import { api } from "../api/client";
import type {
  Fit,
  FitPage,
  MatchedPosting,
  MatchedPostingPage,
  OpeningFit,
  OwnPosting,
  PlanSummary,
  PlanSummaryPage,
  QuestionSet,
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
  StatTile,
} from "../components/ui";
import {
  type AdvisorTab,
  type Focus,
  type RoleFocus,
  roleFocus,
} from "../shell/navigation";
import { useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import {
  getPreviousTargets,
  getStoredTargets,
  type PreviousTarget,
  recordTargetUse,
} from "./advisorTarget";
import { AdvisorNoTarget } from "./AdvisorNoTarget";
import { FillTheGap } from "./FillTheGap";
import { GapPlan } from "./GapPlan";
import { OwnRole, statusLine, useOwnPostings } from "./OwnRole";
import { PreviousTargets } from "./PreviousTargets";
import { Resume } from "./Resume";
import { Credit, pickBand } from "./Roles";
import { type AdvisorTarget, sameTarget, targetQuery } from "./target";
import { messageOf, useAsync } from "./useAsync";

/**
 * The Advisor: Fill the gap first, then either the gap plan or the tailored
 * résumé, for one Target (ADR 0023).
 *
 * The Target is carried in the hash: a role from the role map — and an
 * opening in it, if one was picked there (ADR 0070) — or a role the user
 * brought themselves (Phase 8). That one comes from "Use your own role" (the
 * `own` tab): it is added there, never on the role map, and set as the target
 * there, which reads and scores it (ADR 0034).
 *
 * No Target exists until the user sets one (ADR 0050). Until then the Advisor
 * is "No target yet"; the Target last worked against is remembered in this
 * browser, and the ones before it are offered again as Previous targets.
 */
export function Advisor({ tab }: { tab: AdvisorTab }) {
  const { focus, navigate, account } = useShell();
  const flash = useToast();
  const { settled } = useActivity();
  const picked = roleFocus(focus);
  const roles = useAsync<Role[]>(() => api.items<RolePage>("/roles"), []);
  const fits = useAsync<Fit[]>(() => api.items<FitPage>("/fits"), []);
  const openings = useAsync<MatchedPosting[]>(
    () =>
      picked
        ? api.items<MatchedPostingPage>(
            `/matched-postings?${new URLSearchParams({ role_id: picked.role })}`,
          )
        : Promise.resolve([]),
    [picked?.role],
  );
  // An opening's own fit, scored by its gap analysis (ADR 0073): read again
  // when an Advisor job ends, since that may be the one that scored it.
  const openingFit = useAsync<OpeningFit | null>(
    () =>
      picked?.opening
        ? api.get<OpeningFit | null>(
            `/opening-fit?${new URLSearchParams({ job_posting_id: picked.opening })}`,
          )
        : Promise.resolve(null),
    [picked?.opening, settled.advisor],
  );
  const own = useOwnPostings();
  const plans = useAsync<PlanSummary[]>(
    () => api.items<PlanSummaryPage>("/gap-plans"),
    [],
  );
  const resumes = useAsync<ResumeSummary[]>(
    () => api.items<ResumeSummaryPage>("/tailored-resumes"),
    [],
  );

  const failed =
    roles.error ??
    fits.error ??
    openings.error ??
    openingFit.error ??
    plans.error ??
    resumes.error ??
    own.error;
  if (failed) return <ErrorNote error={failed} />;
  if (
    !roles.data ||
    !fits.data ||
    !openings.data ||
    !plans.data ||
    !resumes.data ||
    !own.data
  ) {
    return <Loading what="the Advisor" />;
  }

  const target = !focus
    ? null
    : "posting" in focus
      ? ownTargetFor(focus.posting, own.data)
      : targetFor(
          focus,
          roles.data,
          fits.data,
          openings.data,
          openingFit.data ?? null,
        );
  const previous = getPreviousTargets({
    history: getStoredTargets(account).history,
    plans: plans.data,
    resumes: resumes.data,
    roles: roles.data,
    fits: fits.data,
    own: own.data,
    current: target?.ref ?? null,
  });

  /** Work against a Target again: what was written for it opens as it was. */
  function switchTo(entry: PreviousTarget) {
    recordTargetUse(account, entry.ref, entry.label);
    navigate("advisor", { tab: "gaps", focus: focusOf(entry.ref) });
  }

  if (tab === "own") {
    return (
      <OwnRole
        own={{ data: own.data, reload: own.reload }}
        currentTarget={target?.label ?? null}
      />
    );
  }

  /** Reopen a plan or résumé kept for another Target. */
  function revisit(ref: TargetRef) {
    if (ref.private_job_posting_id) {
      if (
        !(own.data ?? []).some(
          (posting) =>
            posting.private_job_posting_id === ref.private_job_posting_id,
        )
      ) {
        flash("That posting has been removed, so there is nothing to aim at.");
        return;
      }
    } else if (!(roles.data ?? []).some((role) => role.id === ref.role_id)) {
      flash(
        "That role is no longer on your map, so there is nothing to aim at.",
      );
      return;
    }
    navigate("advisor", { focus: focusOf(ref) });
  }

  if (!focus) {
    return (
      <AdvisorNoTarget
        roles={roles.data}
        fits={fits.data}
        previous={previous}
        onOpenMap={() => navigate("roles")}
        onAddOwn={() => navigate("advisor", { tab: "own" })}
        onUseAgain={switchTo}
      />
    );
  }

  if (!target) {
    if ("posting" in focus) {
      const posting = own.data.find(
        (p) => p.private_job_posting_id === focus.posting,
      );
      const status = posting ? statusLine(posting) : null;
      return (
        <section>
          <EmptyState
            title={
              !posting
                ? "That role has been removed"
                : posting.status === "running"
                  ? `Reading and scoring ${posting.title}`
                  : `${posting.title} is not ready to plan for yet`
            }
          >
            {!posting
              ? "Pick another role of your own, or a role on the role map."
              : posting.status === "running"
                ? "Fill the gap opens here once your fit to it is scored. You don't need to wait on this page."
                : posting.status === "failed"
                  ? `Scoring it did not finish: ${status}. Set it as your target again to retry.`
                  : "Set it as your target to read it and score your fit."}
            <span className="row" style={{ marginTop: 14, gap: 10 }}>
              <Button
                variant={
                  posting?.status === "running" ? "secondary" : "primary"
                }
                onClick={() => navigate("advisor", { tab: "own" })}
              >
                Your own roles
              </Button>
              <Button variant="ghost" onClick={() => navigate("roles")}>
                Pick from role map
              </Button>
            </span>
          </EmptyState>
        </section>
      );
    }
    return (
      <EmptyState title="That target is no longer on your role map">
        The role, or the opening in it, has left the map since you picked it.
        <span className="row" style={{ marginTop: 14, gap: 10 }}>
          <Button onClick={() => navigate("roles")}>Pick from role map</Button>
          <Button
            variant="secondary"
            onClick={() => navigate("advisor", { tab: "own" })}
          >
            Use your own role
          </Button>
        </span>
      </EmptyState>
    );
  }

  return (
    <Aimed
      key={`${target.ref.role_id ?? ""}:${target.ref.job_posting_id ?? ""}:${target.ref.private_job_posting_id ?? ""}`}
      target={target}
      tab={tab}
      plans={plans.data}
      resumes={resumes.data}
      previous={previous}
      onPlansChanged={() => void plans.reload()}
      onResumesChanged={() => void resumes.reload()}
      onRevisit={revisit}
      onSwitch={switchTo}
    />
  );
}

/** The Advisor for one Target. Remounted when the Target changes. */
function Aimed({
  target,
  tab,
  plans,
  resumes,
  previous,
  onPlansChanged,
  onResumesChanged,
  onRevisit,
  onSwitch,
}: {
  target: AdvisorTarget;
  tab: AdvisorTab;
  plans: PlanSummary[];
  resumes: ResumeSummary[];
  previous: PreviousTarget[];
  onPlansChanged: () => void;
  onResumesChanged: () => void;
  onRevisit: (ref: TargetRef) => void;
  onSwitch: (target: PreviousTarget) => void;
}) {
  const { navigate, setTarget, account } = useShell();
  const { activity, refresh, settled } = useActivity();
  // The Advisor's jobs for this Target, from the one poll the shell runs
  // (ADR 0042): a tab whose job runs shows its card, every tab its spinner.
  const jobs = jobsFor(activity, target.ref);
  const jobOn = (which: AdvisorTab) =>
    jobs.find((j) => jobTab(j.kind) === which);
  const running = tab === "own" ? undefined : jobOn(tab);
  const elsewhere = jobs.filter((j) => jobTab(j.kind) !== tab);
  // An opening is planned and written for against its own fit, scored by its
  // gap analysis; before that the plan and résumé have nothing to stand on,
  // unless one was drafted for it already (ADR 0073).
  const isUnscoredOpening =
    target.ref.job_posting_id != null && target.fit === null;
  const hasDrafted = (entries: { target: TargetRef }[]) =>
    entries.some((entry) => sameTarget(entry.target, target.ref));

  // Fill the gap comes first: the plan and résumé warn until its answers are
  // submitted, read again when a job ends or answers go in. Undefined until
  // the first read, so neither tab flashes a warning it then takes back.
  const [gapSet, setGapSet] = useState<QuestionSet | null | undefined>(
    undefined,
  );
  const [gapSetError, setGapSetError] = useState<string | null>(null);
  const [answersSubmitted, setAnswersSubmitted] = useState(0);
  const [draftAnyway, setDraftAnyway] = useState<AdvisorTab[]>([]);
  const gapQuery = targetQuery(target.ref);
  useEffect(() => {
    let isCurrent = true;
    api.get<QuestionSet | null>(`/gap-question-sets/current?${gapQuery}`).then(
      (set) => {
        if (!isCurrent) return;
        setGapSet(set);
        setGapSetError(null);
      },
      (caught: unknown) => {
        if (isCurrent) setGapSetError(messageOf(caught));
      },
    );
    return () => {
      isCurrent = false;
    };
  }, [gapQuery, settled.advisor, answersSubmitted]);
  const gapFill = getGapFillState(gapSet ?? null);
  const isGapFilled = gapFill.kind === "submitted";

  // A job that ended changed a plan or a résumé: the lists read it again.
  useEffect(() => {
    if (settled.advisor === 0) return;
    onPlansChanged();
    onResumesChanged();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled.advisor]);

  // Working against it is using it: it is the Target the Advisor opens on
  // next time, and the newest of the previous ones after another is set.
  const refKey = useMemo(
    () =>
      `${target.ref.role_id ?? ""}:${target.ref.job_posting_id ?? ""}:${target.ref.private_job_posting_id ?? ""}`,
    [target.ref],
  );
  useEffect(() => {
    recordTargetUse(account, target.ref, target.label);
    // Once per Target: the component is keyed on it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, refKey]);

  // The header's chip names the Target both tabs are aimed at.
  useEffect(() => {
    setTarget(
      `${target.label}${target.fit !== null ? ` · ${target.fit}%` : ""}`,
    );
    return () => setTarget(null);
  }, [target, setTarget]);

  return (
    <section>
      <TargetBanner
        target={target}
        previous={previous}
        onPickFromMap={() => navigate("roles")}
        onUseOwn={() => navigate("advisor", { tab: "own" })}
        onSwitch={onSwitch}
      />

      <AdvisorSteps
        tab={tab === "own" ? "gaps" : tab}
        notes={getStepNotes({ gapFill, target, plans, resumes })}
        jobOn={jobOn}
        onPick={(next) => navigate("advisor", { tab: next })}
      />
      <ErrorNote error={gapSetError} />
      {elsewhere[0] && (
        <AdvisorJobNotice
          job={elsewhere[0]}
          onView={() =>
            navigate("advisor", { tab: jobTab(elsewhere[0]!.kind) })
          }
        />
      )}
      {running ? (
        <AdvisorJobCard
          job={running}
          onSwitch={(next) => navigate("advisor", { tab: next })}
          onCancelled={() => void refresh()}
        />
      ) : tab === "gaps" ? (
        <FillTheGap
          target={target}
          onSubmitted={() => {
            setAnswersSubmitted((count) => count + 1);
            onPlansChanged();
            onResumesChanged();
          }}
        />
      ) : gapSet === undefined && gapSetError === null ? (
        <Loading what="Fill the gap" />
      ) : isUnscoredOpening && !hasDrafted(tab === "plan" ? plans : resumes) ? (
        <EmptyState title="Run the gap analysis first">
          {tab === "plan" ? "A gap plan" : "A résumé"} for this opening is
          measured against your fit to it, which its gap analysis scores from
          what the posting asks for.
          <span style={{ display: "block", marginTop: 14 }}>
            <Button onClick={() => navigate("advisor", { tab: "gaps" })}>
              Go to Fill the gap
            </Button>
          </span>
        </EmptyState>
      ) : gapSet !== undefined &&
        !isGapFilled &&
        !hasDrafted(tab === "plan" ? plans : resumes) &&
        !draftAnyway.includes(tab) ? (
        <FillGapFirst
          tab={tab === "resume" ? "resume" : "plan"}
          gapFill={gapFill}
          target={target}
          onFill={() => navigate("advisor", { tab: "gaps" })}
          onDraftAnyway={() => setDraftAnyway([...draftAnyway, tab])}
        />
      ) : (
        <>
          {gapSet !== undefined && !isGapFilled && (
            <FillGapBanner
              onFill={() => navigate("advisor", { tab: "gaps" })}
            />
          )}
          {tab === "plan" ? (
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
        </>
      )}
    </section>
  );
}

/** "Your target role": the one thing every number on this page is about. */
function TargetBanner({
  target,
  previous,
  onPickFromMap,
  onUseOwn,
  onSwitch,
}: {
  target: AdvisorTarget;
  previous: PreviousTarget[];
  onPickFromMap: () => void;
  onUseOwn: () => void;
  onSwitch: (target: PreviousTarget) => void;
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
          <Eyebrow>Your target role</Eyebrow>
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
            {target.postingTitle
              ? "Everything on this page is measured against this opening: what its own posting asks for, read when you analyse its gaps."
              : "Everything on this page is measured against this one role."}
            {target.requirementsEstimated &&
              " What it asks for is estimated from its title, not read from a posting."}
          </p>
        </div>
        <div className="row" style={{ gap: 10, alignItems: "stretch" }}>
          <StatTile
            label="Fit today"
            value={target.fit !== null ? `${target.fit}%` : "—"}
          />
          <StatTile label="Band" value={target.band ?? "—"} />
          <div className="stack" style={{ gap: 8 }}>
            <Button variant="secondary" onClick={onPickFromMap}>
              Pick from role map
            </Button>
            <Button variant="secondary" onClick={onUseOwn}>
              Use your own role
            </Button>
            <PreviousTargets previous={previous} onSwitch={onSwitch} />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The Target a focus names, from the role map's own data; null when the role,
 * or the opening in it, has left the map. An opening's fit is its own, scored
 * by its gap analysis, and none before: never its role's (ADR 0073). Pure.
 */
export function targetFor(
  focus: RoleFocus,
  roles: Role[],
  fits: Fit[],
  openings: MatchedPosting[],
  openingFit: OpeningFit | null = null,
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
  const company = opening?.company_name ?? null;
  return {
    ref: {
      role_id: role.id,
      job_posting_id: opening?.posting_id ?? null,
      private_job_posting_id: null,
    },
    label: company ? `${role.name} · ${company}` : role.name,
    roleName: role.name,
    company,
    location: opening?.location ?? null,
    postingTitle: opening?.title ?? null,
    url: opening?.url ?? null,
    creditedTo: opening?.credited_to ?? null,
    fit: opening
      ? openingFit && openingFit.job_posting_id === opening.posting_id
        ? openingFit.fit
        : null
      : roleFit,
    band: opening?.salary
      ? money(opening.salary.currency, opening.salary.min, opening.salary.max)
      : roleBand
        ? money(roleBand.currency, roleBand.low, roleBand.high)
        : null,
    isOwnPosting: false,
  };
}

/**
 * The Target a role of the user's own names; null when it is gone, or not
 * scored yet, since there is nothing to plan against before it is. A role
 * scored against an earlier analysis is still planned against, as a role on
 * the map is until the map is rebuilt. Pure.
 */
export function ownTargetFor(
  postingId: string,
  postings: OwnPosting[],
): AdvisorTarget | null {
  const posting = postings.find((p) => p.private_job_posting_id === postingId);
  if (!posting || posting.fit === null) return null;
  const company = posting.company_name || null;
  return {
    ref: {
      role_id: null,
      job_posting_id: null,
      private_job_posting_id: posting.private_job_posting_id,
    },
    label: company ? `${posting.title} · ${company}` : posting.title,
    roleName: posting.title,
    company,
    location: null,
    postingTitle: null,
    url: null,
    creditedTo: null,
    fit: posting.fit,
    band: null,
    isOwnPosting: true,
    requirementsEstimated: posting.has_estimated_requirements,
  };
}

/** Where a Target is chosen: on the role map, or among your postings. Pure. */
export function focusOf(ref: TargetRef): Focus {
  if (ref.private_job_posting_id)
    return { posting: ref.private_job_posting_id };
  const role = ref.role_id ?? "";
  return ref.job_posting_id ? { role, opening: ref.job_posting_id } : { role };
}

function money(currency: string, low: number, high: number): string {
  return `${currency} ${Math.round(low / 1000)}k–${Math.round(high / 1000)}k`;
}
