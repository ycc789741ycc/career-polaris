import type { TargetRef } from "../api/types";

/**
 * What the Advisor is aimed at (ADR 0022): one role on the role map, and
 * optionally one opening in it, with what the banner and both tabs show.
 */
export interface AdvisorTarget {
  ref: TargetRef;
  /** "Staff Backend Engineer · Northwind Pay", or the role alone. */
  label: string;
  roleName: string;
  company: string | null;
  location: string | null;
  /** The opening's own title, when the Target names one. */
  postingTitle: string | null;
  url: string | null;
  /** Today's fit: the opening's when there is one, else the role's. */
  fit: number | null;
  /** "EUR 165k–190k", when the opening or role publishes pay. */
  band: string | null;
  /** A role the user added; its JD is its requirements. */
  isCustom: boolean;
}

/** Whether two references name the same Target. Pure. */
export function sameTarget(a: TargetRef, b: TargetRef): boolean {
  return (
    a.role_id === b.role_id &&
    (a.job_posting_id ?? null) === (b.job_posting_id ?? null)
  );
}

/** The query string that names a Target on a cost-estimate route. Pure. */
export function targetQuery(ref: TargetRef): string {
  const params = new URLSearchParams({ role_id: ref.role_id });
  if (ref.job_posting_id) params.set("job_posting_id", ref.job_posting_id);
  return params.toString();
}
