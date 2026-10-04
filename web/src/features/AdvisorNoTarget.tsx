import type { Fit, Role } from "../api/types";
import { AppIcon } from "../components/AppIcon";
import { Button, Eyebrow } from "../components/ui";
import { type PreviousTarget, previousTargetLine } from "./advisorTarget";
import { pickBand } from "./Roles";
import { dayLabel } from "./time";

/** How many previous targets the third card lists. */
const PREVIOUS_SHOWN = 3;

/**
 * The Advisor before a target is set: its steps locked, and the three ways to
 * set one — a role from the map, a role of your own, or a target used before.
 * No target exists until the user chooses one (ADR 0050).
 */
export function AdvisorNoTarget({
  roles,
  fits,
  previous,
  onOpenMap,
  onAddOwn,
  onUseAgain,
}: {
  roles: Role[];
  fits: Fit[];
  previous: PreviousTarget[];
  onOpenMap: () => void;
  onAddOwn: () => void;
  onUseAgain: (target: PreviousTarget) => void;
}) {
  const best = getBestFit(roles, fits);
  return (
    <section className="stack" style={{ gap: 20 }}>
      <section className="no-target-banner" aria-labelledby="no-target-title">
        <AppIcon variant="outline" size={56} />
        <div style={{ minWidth: 0 }}>
          <Eyebrow style={{ color: "var(--color-accent-800)" }}>
            Your target role
          </Eyebrow>
          <h2 id="no-target-title" className="no-target-title">
            Pick a target to get started
          </h2>
          <p className="subcopy" style={{ margin: "6px 0 0" }}>
            The Advisor works against one role at a time. Choose it one of three
            ways below; you can change it later from the banner on every Advisor
            page.
          </p>
        </div>
      </section>

      <nav
        className="row advisor-steps"
        aria-label="Advisor steps (locked until a target is chosen)"
      >
        <span className="eyebrow">First</span>
        <span className="step-locked" aria-disabled="true">
          Fill the gap
        </span>
        <span className="muted" aria-hidden="true">
          →
        </span>
        <span className="eyebrow">Then, either</span>
        <span className="step-locked" aria-disabled="true">
          Gap plan
        </span>
        <span className="step-locked" aria-disabled="true">
          Résumé
        </span>
        <span className="muted" style={{ fontSize: 13 }}>
          Opens once you pick a target
        </span>
      </nav>

      <div className="no-target-cards">
        <div className="panel panel-column">
          <span className="step-number" aria-hidden="true">
            1
          </span>
          <h3 className="no-target-card-title">Pick from role map</h3>
          <p className="subcopy" style={{ margin: 0 }}>
            {roles.length > 0
              ? `Choose one of the ${roles.length} roles matched to your strengths in your locations.`
              : "Your role map is built after an analysis of your strengths. Open it to see where it stands."}
          </p>
          {best && (
            <div className="inset" style={{ marginTop: 14 }}>
              <Eyebrow>Best fit on your map</Eyebrow>
              <div className="row-between" style={{ marginTop: 4 }}>
                <span style={{ fontWeight: 700 }}>{best.role.name}</span>
                {best.fit !== null && (
                  <span className="no-target-fit">{best.fit}%</span>
                )}
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                {[
                  `${best.role.opening_count} ${
                    best.role.opening_count === 1 ? "opening" : "openings"
                  }`,
                  best.band,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
          )}
          <div className="no-target-action">
            <Button onClick={onOpenMap}>Open role map</Button>
          </div>
        </div>

        <div className="panel panel-column">
          <span className="step-number" aria-hidden="true">
            2
          </span>
          <h3 className="no-target-card-title">Use your own role</h3>
          <p className="subcopy" style={{ margin: 0 }}>
            Have a role in mind that isn&apos;t on the map? Upload its job
            description, or type the title and what it asks for.
          </p>
          <div className="no-target-drop">
            PDF, DOCX or TXT · or fill it in by hand
          </div>
          <div className="no-target-action">
            <Button onClick={onAddOwn}>Add your own role</Button>
          </div>
        </div>

        <div className="panel panel-column">
          <span className="step-number" aria-hidden="true">
            3
          </span>
          <h3 className="no-target-card-title">Use a previous target</h3>
          <p className="subcopy" style={{ margin: 0 }}>
            Go back to a role you worked on before. Its answers, gap plan and
            résumé are restored with no new AI calls.
          </p>
          {previous.length === 0 ? (
            <p className="muted" style={{ fontSize: 13, marginTop: 12 }}>
              No previous targets yet.
            </p>
          ) : (
            <ul className="previous-list" aria-label="Previous targets">
              {previous.slice(0, PREVIOUS_SHOWN).map((target) => (
                <li key={targetKey(target)} className="previous-row">
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="ellipsis" style={{ fontWeight: 700 }}>
                      {target.label}
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {previousTargetLine(target, dayLabel)}
                    </div>
                  </div>
                  {target.fit !== null && (
                    <span className="no-target-fit">{target.fit}%</span>
                  )}
                  <Button
                    variant="secondary"
                    onClick={() => onUseAgain(target)}
                    aria-label={`Use ${target.label} again`}
                  >
                    Use again
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <p className="muted" style={{ fontSize: 13, margin: 0 }}>
        Picking a new target writes follow-up questions for it, on your key,
        with the cost shown before it runs. Reusing a previous target costs
        nothing.
      </p>
    </section>
  );
}

/** A stable key for a Target. Pure. */
export function targetKey({ ref }: { ref: PreviousTarget["ref"] }): string {
  return `${ref.role_id ?? ""}:${ref.job_posting_id ?? ""}:${ref.private_job_posting_id ?? ""}`;
}

/** The best-fitting role on the map, with its pay band; none on an empty
 * map. Pure. */
export function getBestFit(
  roles: Role[],
  fits: Fit[],
): { role: Role; fit: number | null; band: string | null } | null {
  const scored = roles.map((role) => ({
    role,
    fit: fits.find((f) => f.role_id === role.id)?.score ?? null,
  }));
  const best = scored.sort((a, b) => (b.fit ?? -1) - (a.fit ?? -1))[0];
  if (!best) return null;
  const band = pickBand(best.role.salary_bands);
  return {
    ...best,
    band: band
      ? `${band.currency} ${Math.round(band.low / 1000)}k–${Math.round(band.high / 1000)}k`
      : null,
  };
}
