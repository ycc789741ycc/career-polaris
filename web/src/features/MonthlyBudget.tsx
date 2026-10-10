import { useState } from "react";
import { api } from "../api/client";
import type { Budget } from "../api/types";
import { AutoGrid, Button, ErrorNote, Field, StatTile } from "../components/ui";
import { messageOf, useAsync } from "./useAsync";

/** The cap on what the user's own key may spend in a month. Shown only while
 * their work runs on it: CareerPolaris AI has its free quota instead. */
export function MonthlyBudget() {
  const budget = useAsync<Budget>(() => api.get("/ai-budget"), []);
  const [cap, setCap] = useState("");

  async function saveCap() {
    try {
      await api.put("/ai-budget", { monthly_cap_usd: cap });
      setCap("");
      await budget.reload();
    } catch (caught) {
      budget.setError(messageOf(caught));
    }
  }

  return (
    <div className="panel">
      <h3>Monthly budget</h3>
      <p className="subcopy">
        Background work spends your money, so it stops at this cap and tells you
        rather than running past it. Calls on a model we have no price for
        aren&apos;t counted toward it.
      </p>
      <ErrorNote error={budget.error} />
      {budget.data && (
        <AutoGrid col={110} gap={10} style={{ margin: "12px 0 14px" }}>
          <StatTile label="Cap" value={`$${budget.data.monthly_cap_usd}`} />
          <StatTile
            label="Spent"
            value={`$${budget.data.spent_this_month_usd}`}
          />
          <StatTile label="Remaining" value={`$${budget.data.remaining_usd}`} />
        </AutoGrid>
      )}
      <div
        className="row"
        style={{ alignItems: "flex-end", flexWrap: "nowrap" }}
      >
        <div style={{ flex: 1 }}>
          <Field label="New monthly cap (USD)">
            <input
              className="input"
              inputMode="decimal"
              value={cap}
              onChange={(event) => setCap(event.target.value)}
            />
          </Field>
        </div>
        <div style={{ paddingBottom: 14 }}>
          <Button variant="secondary" onClick={saveCap} disabled={!cap.trim()}>
            Update
          </Button>
        </div>
      </div>
    </div>
  );
}
