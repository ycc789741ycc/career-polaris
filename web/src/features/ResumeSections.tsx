import { type DragEvent, type KeyboardEvent, useState } from "react";
import type {
  ResumeContent,
  ResumeSection,
  ResumeSectionSlot,
  SectionKind,
} from "../api/types";
import { Button, Eyebrow } from "../components/ui";

/**
 * A résumé's sections (ADR 0039, ADR 0043): every one it holds, in order,
 * each shown or hidden. Generating writes them all, so Show and Hide cost
 * nothing; only shown sections print. The panel lists them with a drag handle
 * (which also moves with the keyboard); Experience is always shown. A section
 * with no lines can be filled from the sources, and "Custom…" adds one of the
 * user's own, both at a price shown first.
 */

/** What each kind is printed under; a custom section prints its own. */
export const SECTION_HEADINGS: Record<SectionKind, string> = {
  summary: "Summary",
  experience: "Experience",
  side_projects: "Side projects",
  open_source: "Open source",
  education: "Education",
  talks_and_writing: "Talks & writing",
  skills: "Skills",
  certifications: "Certifications",
  custom: "",
};

const MAX_CUSTOM = 3;

/** The heading a section prints under: the one the user gave it, or its
 * kind's. Pure. */
export function sectionHeading(section: ResumeSectionSlot): string {
  return section.title?.trim() || SECTION_HEADINGS[section.kind];
}

export function emptySection(slot: ResumeSectionSlot): ResumeSection {
  return {
    kind: slot.kind,
    title: slot.kind === "custom" ? slot.title : null,
    text: "",
    entries: [],
    items: [],
    bullets: [],
    is_shown: slot.is_shown,
  };
}

export function isEmptySection(section: ResumeSection): boolean {
  return (
    !section.text.trim() &&
    section.entries.length === 0 &&
    section.items.length === 0 &&
    section.bullets.length === 0
  );
}

/** The content with section `from` moved by `by` places. Pure. */
export function moveSection(
  content: ResumeContent,
  from: number,
  by: number,
): ResumeContent {
  const to = from + by;
  if (to < 0 || to >= content.sections.length) return content;
  const sections = [...content.sections];
  const [moved] = sections.splice(from, 1);
  sections.splice(to, 0, moved!);
  return { ...content, sections };
}

/** The content without section `at`, which must be one of the user's own:
 * a built-in section is hidden, never removed. Pure. */
export function removeSection(
  content: ResumeContent,
  at: number,
): ResumeContent {
  if (content.sections[at]?.kind !== "custom") return content;
  return {
    ...content,
    sections: content.sections.filter((_, index) => index !== at),
  };
}

/** The content with section `at` shown or hidden; experience is always
 * shown. Pure. */
export function updateShown(
  content: ResumeContent,
  at: number,
  isShown: boolean,
): ResumeContent {
  const section = content.sections[at];
  if (!section || section.kind === "experience") return content;
  return {
    ...content,
    sections: content.sections.map((s, index) =>
      index === at ? { ...s, is_shown: isShown } : s,
    ),
  };
}

export function SectionsPanel({
  content,
  added,
  filling,
  busy,
  onChange,
  onAdd,
}: {
  content: ResumeContent;
  /** Sections added in this visit, marked "New". */
  added: string[];
  /** The section being filled from the sources, if one is. */
  filling: ResumeSectionSlot | null;
  busy: boolean;
  /** Sections moved, shown, hidden or one removed: saved as a version at
   * once, with no spend. */
  onChange: (next: ResumeContent) => void;
  /** Price filling an empty section, or a new one of the user's own, from
   * the sources. */
  onAdd: (slot: ResumeSectionSlot) => void;
}) {
  const [dragging, setDragging] = useState<number | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [customTitle, setCustomTitle] = useState<string | null>(null);
  const customCount = content.sections.filter(
    (s) => s.kind === "custom",
  ).length;

  const onKey = (index: number) => (event: KeyboardEvent) => {
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      event.preventDefault();
      onChange(moveSection(content, index, event.key === "ArrowUp" ? -1 : 1));
    }
  };

  const onDrop = (index: number) => (event: DragEvent) => {
    event.preventDefault();
    if (dragging !== null && dragging !== index) {
      onChange(moveSection(content, dragging, index - dragging));
    }
    setDragging(null);
  };

  const remove = (index: number) => {
    const section = content.sections[index]!;
    if (!isEmptySection(section) && confirming !== index) {
      setConfirming(index);
      return;
    }
    setConfirming(null);
    onChange(removeSection(content, index));
  };

  return (
    <div className="panel panel-tight" role="region" aria-label="Sections">
      <Eyebrow>Sections</Eyebrow>
      <p className="subcopy" style={{ fontSize: 12.5, margin: "4px 0 4px" }}>
        Every section is written; show the ones you want. Drag to reorder.
      </p>
      <ul className="section-list">
        {content.sections.map((section, index) => {
          const name = sectionHeading(section);
          const key = `${section.kind}:${section.title ?? ""}`;
          const isFilling =
            filling !== null &&
            filling.kind === section.kind &&
            (filling.title ?? null) === (section.title ?? null);
          const isEmpty = isEmptySection(section);
          return (
            <li
              key={key}
              className="section-row"
              data-shown={section.is_shown}
              draggable={!busy}
              onDragStart={() => setDragging(index)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={onDrop(index)}
            >
              <button
                type="button"
                className="section-handle"
                aria-label={`Move ${name}`}
                title="Drag, or use the arrow keys"
                disabled={busy}
                onKeyDown={onKey(index)}
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  {[6, 12, 18].flatMap((y) =>
                    [9, 15].map((x) => (
                      <circle key={`${x}-${y}`} cx={x} cy={y} r="1.6" />
                    )),
                  )}
                </svg>
              </button>
              <span className="section-text">
                <span
                  className={
                    section.is_shown ? "section-name" : "section-name muted"
                  }
                  title={name}
                >
                  {name}
                </span>
                {isEmpty && !isFilling && !added.includes(key) && (
                  <button
                    type="button"
                    className="section-fill"
                    title="Nothing in your sources for this yet"
                    disabled={busy || filling !== null}
                    onClick={() =>
                      onAdd({
                        kind: section.kind,
                        title: section.title,
                        is_shown: true,
                      })
                    }
                  >
                    Empty — fill from your sources
                  </button>
                )}
              </span>
              {isFilling ? (
                <span className="chip">Filling…</span>
              ) : (
                added.includes(key) && <span className="chip">New</span>
              )}
              {section.kind === "experience" ? (
                <span className="muted" style={{ fontSize: 12 }}>
                  Required
                </span>
              ) : section.kind === "custom" ? (
                <Button
                  variant="ghost"
                  busy={busy && confirming === index}
                  onClick={() => remove(index)}
                >
                  {confirming === index ? "Remove its lines too" : "Remove"}
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  disabled={busy}
                  aria-pressed={section.is_shown}
                  onClick={() =>
                    onChange(updateShown(content, index, !section.is_shown))
                  }
                >
                  {section.is_shown ? "Hide" : "Show"}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      <div style={{ fontSize: 12, fontWeight: 700, margin: "14px 0 6px" }}>
        Add a section of your own
      </div>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        {customCount < MAX_CUSTOM && customTitle === null && (
          <button
            type="button"
            className="chip-add"
            disabled={busy || filling !== null}
            onClick={() => setCustomTitle("")}
          >
            + Custom…
          </button>
        )}
      </div>
      {customTitle !== null && (
        <form
          className="row"
          style={{ gap: 6, marginTop: 8 }}
          onSubmit={(event) => {
            event.preventDefault();
            const title = customTitle.trim();
            if (!title) return;
            setCustomTitle(null);
            onAdd({ kind: "custom", title, is_shown: true });
          }}
        >
          <input
            className="input"
            aria-label="Heading of your section"
            placeholder="Heading, e.g. Volunteering"
            maxLength={60}
            value={customTitle}
            onChange={(event) => setCustomTitle(event.target.value)}
          />
          <Button type="submit" disabled={!customTitle.trim()}>
            Add
          </Button>
          <Button variant="ghost" onClick={() => setCustomTitle(null)}>
            Cancel
          </Button>
        </form>
      )}
      <p className="subcopy" style={{ fontSize: 12, margin: "10px 0 0" }}>
        Showing or hiding a section is free. Filling one from your sources is
        priced first; add or edit lines in place.
      </p>
    </div>
  );
}
