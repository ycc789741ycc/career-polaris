/** Facts a chart has picked, which the evidence table narrows to. */
export interface FactSelection {
  /** Identifies what was picked, so picking it again can clear it. */
  key: string;
  /** How the table names the picked facts: "acme/ledger", "Week of …". */
  label: string;
  ids: string[];
}
