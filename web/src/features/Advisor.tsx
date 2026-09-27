import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  PlanSummary,
  ResumeSummary,
  TargetKind,
  TargetOption,
} from "../api/types";
import {
  Button,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Loading,
  PillToggle,
} from "../components/ui";
import type { AdvisorTab, Focus } from "../shell/navigation";
import { useShell } from "../shell/ShellContext";
import { useToast } from "../shell/toast";
import { GapPlan } from "./GapPlan";
import { Resume } from "./Resume";
import { useAsync } from "./useAsync";

type Ref = { kind: TargetKind; id: string };

/**
 * The Advisor: the gap plan and the tailored résumé for one Target, as two
 * tabs of one screen.
 *
 * What it aims at is what the role map has selected. A role spans openings at
 * several companies and plans and résumés are kept per opening, so the
 * header offers that role's openings — and the watched roles filed under it —
 * and opens the one last worked on, or the best fit. A pasted JD is its own
 * single opening.
 */
export function Advisor({ tab }: { tab: AdvisorTab }) {
  const { focus, navigate } = useShell();
  const flash = useToast();
  const targets = useAsync<TargetOption[]>(() => api.get("/targets"), []);
  const plans = useAsync<PlanSummary[]>(() => api.get("/gap-plans"), []);
  const resumes = useAsync<ResumeSummary[]>(
    () => api.get("/tailored-resumes"),
    [],
  );
  // An opening a history entry asked for, opened once its focus is showing.
  const [wanted, setWanted] = useState<Ref | null>(null);

  if (!focus) {
    return (
      <EmptyState title="Pick a role on the role map first">
        The Advisor plans a route to — and writes your résumé for — whatever you
        select there: a role, or a job description you pasted.
        <span style={{ display: "block", marginTop: 14 }}>
          <Button onClick={() => navigate("roles")}>Open the role map</Button>
        </span>
      </EmptyState>
    );
  }

  const failed = targets.error ?? plans.error ?? resumes.error;
  if (failed) return <ErrorNote error={failed} />;
  if (!targets.data || !plans.data || !resumes.data) {
    return <Loading what="the Advisor" />;
  }

  /** Reopen a plan or résumé kept for a Target outside the current focus. */
  function revisit(ref: Ref) {
    const option = (targets.data ?? []).find((o) => sameTarget(o, ref));
    const next = option ? focusOf(option) : null;
    if (!option || !next) {
      flash("That opening is no longer listed, so there is nothing to aim at.");
      return;
    }
    setWanted(ref);
    navigate("advisor", { focus: next });
  }

  return (
    <Aimed
      key={`${focus.kind}:${focus.id}`}
      focus={focus}
      tab={tab}
      targets={targets.data}
      plans={plans.data}
      resumes={resumes.data}
      wanted={wanted}
      onPlansChanged={() => {
        void plans.reload();
        void targets.reload();
      }}
      onResumesChanged={() => {
        void resumes.reload();
        void targets.reload();
      }}
      onRevisit={revisit}
    />
  );
}

/** The Advisor for one focus. Remounted when the focus changes. */
function Aimed({
  focus,
  tab,
  targets,
  plans,
  resumes,
  wanted,
  onPlansChanged,
  onResumesChanged,
  onRevisit,
}: {
  focus: Focus;
  tab: AdvisorTab;
  targets: TargetOption[];
  plans: PlanSummary[];
  resumes: ResumeSummary[];
  wanted: Ref | null;
  onPlansChanged: () => void;
  onResumesChanged: () => void;
  onRevisit: (ref: Ref) => void;
}) {
  const { navigate, setTarget } = useShell();
  const options = openingsFor(focus, targets);
  const [chosen, setChosen] = useState<Ref | null>(() =>
    firstOpening(options, plans, resumes, wanted),
  );
  const target = options.find((o) => chosen && sameTarget(o, chosen));

  // The header's chip names the opening both tabs are aimed at.
  useEffect(() => {
    setTarget(
      target
        ? `${target.label}${target.fit !== null ? ` · ${target.fit}%` : ""}`
        : null,
    );
    return () => setTarget(null);
  }, [target, setTarget]);

  /** A history entry: switch opening here, or move the Advisor to its role. */
  function revisit(ref: Ref) {
    if (options.some((o) => sameTarget(o, ref))) setChosen(ref);
    else onRevisit(ref);
  }

  const heading =
    focus.kind === "jd"
      ? (options[0]?.title ?? "Your pasted JD")
      : (options[0]?.role_name ?? "The selected role");

  return (
    <section>
      <div className="panel panel-tight" style={{ marginBottom: 20 }}>
        <div
          className="row-between"
          style={{ alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}
        >
          <div>
            <Eyebrow>Aiming at</Eyebrow>
            <div
              style={{
                fontFamily: "var(--font-heading)",
                fontSize: 20,
                marginTop: 4,
              }}
            >
              {heading}
            </div>
          </div>
          <Button variant="ghost" onClick={() => navigate("roles")}>
            Change role
          </Button>
        </div>
        {options.length === 0 ? (
          <p className="subcopy" style={{ margin: 0 }}>
            {focus.kind === "jd"
              ? "That job description is no longer saved."
              : "This role has no open postings or watched companies right now."}{" "}
            Pick another on the role map, or watch a company for this role
            there.
          </p>
        ) : (
          <>
            {focus.kind === "role" && (
              <p className="subcopy" style={{ margin: "0 0 10px" }}>
                Plans and résumés are kept per company. Pick the opening to aim
                at.
              </p>
            )}
            <TargetChips
              options={options}
              selected={chosen}
              onSelect={setChosen}
            />
          </>
        )}
      </div>

      {target && (
        <>
          <div
            className="row"
            role="group"
            aria-label="Advisor tabs"
            style={{ marginBottom: 20 }}
          >
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
          {tab === "plan" ? (
            <GapPlan
              key={`${target.kind}:${target.id}`}
              target={target}
              history={plans}
              onChanged={onPlansChanged}
              onRevisit={(entry) => revisit(entry.target)}
            />
          ) : (
            <Resume
              key={`${target.kind}:${target.id}`}
              target={target}
              saved={resumes}
              onChanged={onResumesChanged}
              onRevisit={(entry) => revisit(entry.target)}
            />
          )}
        </>
      )}
    </section>
  );
}

function TargetChips({
  options,
  selected,
  onSelect,
}: {
  options: TargetOption[];
  selected: Ref | null;
  onSelect: (ref: Ref) => void;
}) {
  return (
    <div className="row" style={{ gap: 8 }}>
      {options.map((option) => (
        <button
          key={`${option.kind}:${option.id}`}
          type="button"
          className="target-chip"
          aria-pressed={!!selected && sameTarget(option, selected)}
          onClick={() => onSelect({ kind: option.kind, id: option.id })}
        >
          <b>{option.role_name ?? option.title}</b>
          <span className="target-chip-company">{option.company_name}</span>
          {option.fit !== null && (
            <span className="target-chip-fit">{option.fit}%</span>
          )}
          {option.kind === "subscription" && (
            <span className="target-chip-tag">subscribed</span>
          )}
        </button>
      ))}
    </div>
  );
}

/** The Targets a focus offers: a role's openings and watches, or one JD. Pure. */
export function openingsFor(
  focus: Focus,
  targets: TargetOption[],
): TargetOption[] {
  return focus.kind === "jd"
    ? targets.filter((o) => o.kind === "privatePosting" && o.id === focus.id)
    : targets.filter(
        (o) => o.kind !== "privatePosting" && o.role_id === focus.id,
      );
}

/**
 * The opening to show first: one a history entry asked for, else the one
 * with the most recent plan or résumé, else the best fit. Pure.
 */
export function firstOpening(
  options: TargetOption[],
  plans: PlanSummary[],
  resumes: ResumeSummary[],
  wanted: Ref | null = null,
): Ref | null {
  const listed = (ref: Ref | null) =>
    ref ? options.find((o) => sameTarget(o, ref)) : undefined;
  const worked = [
    ...plans.map((p) => ({ ref: p.target, at: p.drafted_at ?? p.created_at })),
    ...resumes.map((r) => ({ ref: r.target, at: r.updated_at })),
  ]
    .filter((entry) => listed(entry.ref))
    .sort((a, b) => b.at.localeCompare(a.at));
  const best = [...options].sort((a, b) => (b.fit ?? -1) - (a.fit ?? -1))[0];
  const pick = listed(wanted) ?? listed(worked[0]?.ref ?? null) ?? best;
  return pick ? { kind: pick.kind, id: pick.id } : null;
}

/** Where on the role map a Target sits, if anywhere. Pure. */
function focusOf(option: TargetOption): Focus | null {
  if (option.kind === "privatePosting") return { kind: "jd", id: option.id };
  return option.role_id ? { kind: "role", id: option.role_id } : null;
}

function sameTarget(a: Ref, b: Ref): boolean {
  return a.kind === b.kind && a.id === b.id;
}
