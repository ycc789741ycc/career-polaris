import { useMemo, useState, type CSSProperties } from "react";
import type { Evidence } from "../api/types";
import { PillToggle } from "../components/ui";
import type { FactSelection } from "./selection";
import {
  SPARSE_BELOW,
  addDays,
  buildTimeline,
  formatDate,
  formatMonth,
  heatLevel,
  position,
  todayUtc,
  type Timeline,
  type TimelineRange,
  type TimelineRow,
} from "./timeline";

interface Props {
  facts: Evidence[];
  /** YYYY-MM-DD; the chart ends with the week this falls in. */
  today?: string;
  selectedKey?: string | null;
  onSelect: (selection: FactSelection | null) => void;
}

interface Readout {
  title: string;
  detail: string;
}

/** Past this many weeks, only quarter months are labelled. */
const DENSE_WEEKS = 60;
const REFERENCES_SHOWN = 3;

/**
 * When the work happened: one row per source, one cell per week.
 *
 * An HTML grid rather than SVG: cells shrink to fit the column, while labels
 * keep their size, which a scaled viewBox would not. A quiet week is a pale
 * cell and nothing more — it may be leave, a new job or private work, and this
 * page is not the place to judge it.
 */
export function EvidenceTimeline({
  facts,
  today = todayUtc(),
  selectedKey = null,
  onSelect,
}: Props) {
  const [range, setRange] = useState<TimelineRange>("year");
  const [readout, setReadout] = useState<Readout | null>(null);
  const timeline = useMemo(
    () => buildTimeline(facts, { today, range }),
    [facts, today, range],
  );
  // Jira issues synced before issues carried dates wait for the next sync.
  const isJiraAwaitingDates = facts.some(
    (f) =>
      f.source === "jira" && f.granularity === "item" && f.observed_on === null,
  );

  function toggle(selection: FactSelection) {
    onSelect(selection.key === selectedKey ? null : selection);
  }

  const isSparse = timeline.dated < SPARSE_BELOW;
  const weekCount = timeline.weeks.length;
  const lastDay = addDays(timeline.weeks[weekCount - 1] as string, 6);

  return (
    <div className="panel">
      <div className="row-between" style={{ alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>When the work happened</h3>
        <div className="row" role="group" aria-label="Time range">
          <PillToggle
            small
            pressed={range === "year"}
            onClick={() => setRange("year")}
          >
            12 months
          </PillToggle>
          <PillToggle
            small
            pressed={range === "all"}
            onClick={() => setRange("all")}
          >
            Everything
          </PillToggle>
        </div>
      </div>
      <p className="subcopy" style={{ fontSize: 13 }}>
        {isSparse ? "Each dot" : "Each cell is a week, and each"} pull request
        or issue counts once. Totals like “12 merged pull requests” are left
        out, so nothing counts twice.
      </p>

      <div className="table-scroll">
        <div
          className="timeline"
          style={
            {
              "--timeline-weeks": weekCount,
              minWidth: weekCount > DENSE_WEEKS ? weekCount * 7 + 140 : 0,
            } as CSSProperties
          }
        >
          {monthLabels(timeline.weeks).map(({ index, text }) => (
            <div
              key={index}
              className="timeline-month"
              aria-hidden="true"
              style={{ gridRow: 1, gridColumn: `${index + 2} / span 4` }}
            >
              {text}
            </div>
          ))}

          {timeline.rows.map((row, rowIndex) => {
            const gridRow = rowIndex + 2;
            const rowFacts = row.weeks.flatMap((w) => w.facts);
            const rowSelection = {
              key: row.source,
              label: `${row.label} · ${rangeName(range)}`,
              ids: rowFacts.map((f) => f.id),
            };
            return [
              <button
                key={`${row.source}-label`}
                type="button"
                className="timeline-label"
                style={{ gridRow, gridColumn: 1 }}
                aria-pressed={selectedKey === row.source}
                disabled={row.total === 0}
                onClick={() => toggle(rowSelection)}
              >
                {row.label}
              </button>,
              row.total === 0 ? (
                <div
                  key={`${row.source}-empty`}
                  className="timeline-empty muted"
                  style={{ gridRow, gridColumn: `2 / span ${weekCount}` }}
                >
                  {row.source === "jira" && isJiraAwaitingDates
                    ? "Dates arrive at your next Jira sync."
                    : `No ${row.noun[1]} ${range === "year" ? "in the last 12 months" : "yet"}.`}
                </div>
              ) : isSparse ? (
                <div
                  key={`${row.source}-track`}
                  className="timeline-track"
                  style={{ gridRow, gridColumn: `2 / span ${weekCount}` }}
                >
                  {rowFacts.map((fact) => {
                    const readoutFor = factReadout(fact);
                    return (
                      <button
                        key={fact.id}
                        type="button"
                        className="timeline-dot"
                        style={{
                          left: `${position(fact.observed_on as string, timeline.weeks[0] as string, lastDay) * 100}%`,
                        }}
                        aria-label={`${readoutFor.title}: ${readoutFor.detail}`}
                        aria-pressed={selectedKey === fact.id}
                        onClick={() =>
                          toggle({
                            key: fact.id,
                            label: fact.reference,
                            ids: [fact.id],
                          })
                        }
                        onMouseEnter={() => setReadout(readoutFor)}
                        onMouseLeave={() => setReadout(null)}
                        onFocus={() => setReadout(readoutFor)}
                        onBlur={() => setReadout(null)}
                      />
                    );
                  })}
                </div>
              ) : (
                row.weeks.map((week, weekIndex) => {
                  const style = { gridRow, gridColumn: weekIndex + 2 };
                  const level = heatLevel(week.facts.length);
                  if (level === 0) {
                    return (
                      <span
                        key={`${row.source}-${week.start}`}
                        className="timeline-cell"
                        data-level={0}
                        style={style}
                        aria-hidden="true"
                      />
                    );
                  }
                  const key = `${row.source}:${week.start}`;
                  const readoutFor = weekReadout(row, week.start, week.facts);
                  return (
                    <button
                      key={key}
                      type="button"
                      className="timeline-cell"
                      data-level={level}
                      style={style}
                      aria-label={`${readoutFor.title}: ${readoutFor.detail}`}
                      aria-pressed={selectedKey === key}
                      onClick={() =>
                        toggle({
                          key,
                          label: `${row.label} · ${readoutFor.title.toLowerCase()}`,
                          ids: week.facts.map((f) => f.id),
                        })
                      }
                      onMouseEnter={() => setReadout(readoutFor)}
                      onMouseLeave={() => setReadout(null)}
                      onFocus={() => setReadout(readoutFor)}
                      onBlur={() => setReadout(null)}
                    />
                  );
                })
              ),
              <div
                key={`${row.source}-total`}
                className="timeline-total"
                style={{ gridRow, gridColumn: weekCount + 2 }}
              >
                {row.total}
              </div>,
            ];
          })}
        </div>
      </div>

      <div className="timeline-readout" aria-hidden="true">
        {readout ? (
          <>
            <strong>{readout.title}</strong> · {readout.detail}
          </>
        ) : (
          <span className="muted">
            Hover or focus a {isSparse ? "dot" : "week"} to see what is in it;
            click to list it below.
          </span>
        )}
      </div>

      <div
        className="row-between"
        style={{ marginTop: 12, alignItems: "flex-start", gap: 16 }}
      >
        <p className="subcopy" style={{ fontSize: 13, margin: 0 }}>
          {summary(timeline)}
          {range === "year" && timeline.older > 0 && (
            <>
              {" "}
              <button
                type="button"
                className="link-button"
                onClick={() => setRange("all")}
              >
                Show {factCount(timeline.older)} from earlier
              </button>
            </>
          )}
        </p>
        {!isSparse && <HeatLegend />}
      </div>

      <MonthTable timeline={timeline} />
    </div>
  );
}

function HeatLegend() {
  return (
    <div className="timeline-legend" aria-hidden="true">
      <span>Fewer</span>
      {[0, 1, 2, 3].map((level) => (
        <span key={level} className="timeline-cell" data-level={level} />
      ))}
      <span>More</span>
    </div>
  );
}

/** The chart's numbers for a screen reader: dated facts per month. */
function MonthTable({ timeline }: { timeline: Timeline }) {
  const months = [
    ...new Set(
      timeline.rows.flatMap((row) =>
        row.weeks.flatMap((w) =>
          w.facts.map((f) => (f.observed_on as string).slice(0, 7)),
        ),
      ),
    ),
  ].sort();
  if (months.length === 0) return null;
  return (
    <table className="sr-only">
      <caption>Dated work per month</caption>
      <thead>
        <tr>
          <th scope="col">Month</th>
          {timeline.rows.map((row) => (
            <th key={row.source} scope="col">
              {row.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {months.map((month) => (
          <tr key={month}>
            <th scope="row">{formatMonth(month)}</th>
            {timeline.rows.map((row) => (
              <td key={row.source}>
                {
                  row.weeks
                    .flatMap((w) => w.facts)
                    .filter((f) => (f.observed_on as string).startsWith(month))
                    .length
                }
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function monthLabels(weeks: string[]): { index: number; text: string }[] {
  const isDense = weeks.length > DENSE_WEEKS;
  const labels: { index: number; text: string }[] = [];
  let previous = "";
  weeks.forEach((week, index) => {
    // A week belongs to the month its Thursday is in, as ISO weeks do, so a
    // label never sits over a week that is mostly the month before.
    const month = addDays(week, 3).slice(0, 7);
    if (month === previous) return;
    previous = month;
    const monthNumber = Number(month.slice(5, 7));
    if (isDense && (monthNumber - 1) % 3 !== 0) return;
    const isYearStart = monthNumber === 1 || labels.length === 0;
    const text = formatMonth(month);
    labels.push({
      index,
      text: isYearStart ? text : (text.split(" ")[0] as string),
    });
  });
  return labels;
}

function weekReadout(
  row: TimelineRow,
  start: string,
  facts: Evidence[],
): Readout {
  const count = facts.length;
  const noun = row.noun[count === 1 ? 0 : 1];
  const shown = facts.slice(0, REFERENCES_SHOWN).map(shortReference);
  const more = count - shown.length;
  return {
    title: `Week of ${formatDate(start)}`,
    detail: `${count} ${noun} · ${shown.join(", ")}${more > 0 ? `, +${more} more` : ""}`,
  };
}

function factReadout(fact: Evidence): Readout {
  return {
    title: formatDate(fact.observed_on as string),
    detail: `${shortReference(fact)} · ${fact.fact}`,
  };
}

/** "acme/ledger#214" from "GitHub · acme/ledger#214". */
function shortReference(fact: Evidence): string {
  return fact.reference.split(" · ").at(-1) ?? fact.reference;
}

function summary(timeline: Timeline): string {
  const parts: string[] = [];
  const [first, second] = timeline.busiestMonths;
  if (first) {
    const busiest = [first, second]
      .filter((m) => m !== undefined)
      .map((m) => `${formatMonth(m.month)} (${m.count})`)
      .join(" and ");
    parts.push(`Most active: ${busiest}.`);
  }
  if (timeline.undated > 0) {
    parts.push(
      `${factCount(timeline.undated)} ${timeline.undated === 1 ? "has" : "have"} no work date (such as résumé lines and your answers) and ${timeline.undated === 1 ? "is" : "are"} not shown.`,
    );
  }
  return parts.join(" ");
}

function rangeName(range: TimelineRange): string {
  return range === "year" ? "last 12 months" : "everything";
}

function factCount(count: number): string {
  return `${count} ${count === 1 ? "fact" : "facts"}`;
}
