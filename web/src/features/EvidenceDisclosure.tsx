/** One piece of evidence, as a disclosure shows it. */
export interface DisclosedEvidence {
  id?: string;
  reference: string;
  fact: string;
}

/**
 * Evidence is detail: shown collapsed, opened on demand (domain spec §7).
 * The count in the label says there is evidence before it is opened. Its
 * open state is not remembered between visits.
 */
export function EvidenceDisclosure({
  evidence,
  compact = false,
  empty,
}: {
  evidence: DisclosedEvidence[];
  /** "Evidence ▾", for a row too narrow for the count. */
  compact?: boolean;
  /** What an empty one says when opened. */
  empty: string;
}) {
  const label = compact
    ? "Evidence ▾"
    : `Show evidence (${evidence.length === 0 ? "none found" : evidence.length})`;
  return (
    <details className="evidence-disclosure">
      <summary>{label}</summary>
      {evidence.length === 0 ? (
        <p className="evidence-empty">{empty}</p>
      ) : (
        evidence.map((item, index) => (
          <div
            key={item.id ?? `${item.reference}-${index}`}
            className="evidence-item"
          >
            <div className="evidence-reference">{item.reference}</div>
            <div className="evidence-fact">{item.fact}</div>
          </div>
        ))
      )}
    </details>
  );
}
