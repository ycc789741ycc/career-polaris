import type { TargetRef } from "../api/types";

/**
 * What the Advisor is aimed at: one role on the role map and optionally one
 * opening in it (ADR 0022), or a posting the user brought themselves
 * (Phase 8), with what the banner and every tab show.
 */
export interface AdvisorTarget {
  ref: TargetRef;
  /** "Staff Backend Engineer · Northwind Pay", or the role alone. */
  label: string;
  /** The role's name, or a posting of your own's title. */
  roleName: string;
  company: string | null;
  location: string | null;
  /** The opening's own title, when the Target names one. */
  postingTitle: string | null;
  url: string | null;
  /** The job site the opening was found through, to credit beside it. */
  creditedTo: string | null;
  /** Today's fit: the opening's when there is one, else the role's. */
  fit: number | null;
  /** "EUR 165k–190k", when the opening or role publishes pay. */
  band: string | null;
  /** A posting the user brought themselves; its JD is its requirements. */
  isOwnPosting: boolean;
}

/** Whether two references name the same Target. Pure. */
export function sameTarget(a: TargetRef, b: TargetRef): boolean {
  return (
    (a.role_id ?? null) === (b.role_id ?? null) &&
    (a.job_posting_id ?? null) === (b.job_posting_id ?? null) &&
    (a.private_job_posting_id ?? null) === (b.private_job_posting_id ?? null)
  );
}

/** The query string that names a Target on a cost-estimate route. Pure. */
export function targetQuery(ref: TargetRef): string {
  const params = new URLSearchParams();
  if (ref.role_id) params.set("role_id", ref.role_id);
  if (ref.job_posting_id) params.set("job_posting_id", ref.job_posting_id);
  if (ref.private_job_posting_id) {
    params.set("private_job_posting_id", ref.private_job_posting_id);
  }
  return params.toString();
}
