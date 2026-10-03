import { type DragEvent, type KeyboardEvent, useState } from "react";
import type {
  ResumeContent,
  ResumeSection,
  ResumeSectionSlot,
  SectionKind,
} from "../api/types";
import { Button, Eyebrow } from "../components/ui";

/**
 * A résumé's sections (ADR 0039): which there are, in what order. The panel
 * lists them with a drag handle (which also moves with the keyboard) and
 * Remove; Experience is required. "Add a section" offers the kinds not there
 * yet, and Custom…, each filled from the sources at a price shown first.
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

/** The kinds "Add a section" offers, in the prototype's order. */
const ADDABLE: SectionKind[] = [
  "summary",
  "side_projects",
  "education",
  "talks_and_writing",
  "open_source",
  "certifications",
  "skills",
];

const MAX_CUSTOM = 3;

export function sectionHeading(section: ResumeSectionSlot): string {
  return section.kind === "custom"
    ? (section.title ?? "")
    : SECTION_HEADINGS[section.kind];
}

export function emptySection(slot: ResumeSectionSlot): ResumeSection {
  return {
    kind: slot.kind,
    title: slot.kind === "custom" ? slot.title : null,
    text: "",
    entries: [],
    items: [],
    bullets: [],
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

/** The content without section `at`; experience never goes. Pure. */
export function removeSection(
  content: ResumeContent,
  at: number,
): ResumeContent {
  if (content.sections[at]?.kind === "experience") return content;
  return {
    ...content,
    sections: content.sections.filter((_, index) => index !== at),
  };
}

/** The kinds a résumé can still take. Pure. */
export function addableKinds(content: ResumeContent): SectionKind[] {
  const present = new Set(content.sections.map((s) => s.kind));
  return ADDABLE.filter((kind) => !present.has(kind));
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
  /** The sections moved or one removed: saved as a version at once. */
  onChange: (next: ResumeContent) => void;
  /** Price filling a new section from the sources. */
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
        Drag to reorder. Remove what you don&apos;t need.
      </p>
      <ul className="section-list">
        {content.sections.map((section, index) => {
          const name = sectionHeading(section);
          const key = `${section.kind}:${section.title ?? ""}`;
          const isFilling =
            filling !== null &&
            filling.kind === section.kind &&
            (filling.title ?? null) === (section.title ?? null);
          return (
            <li
              key={key}
              className="section-row"
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
              <span className="section-name">{name}</span>
              {isFilling ? (
                <span className="chip">Filling…</span>
              ) : (
                added.includes(key) && <span className="chip">New</span>
              )}
              {section.kind === "experience" ? (
                <span className="muted" style={{ fontSize: 12 }}>
                  Required
                </span>
              ) : (
                <Button
                  variant="ghost"
                  busy={busy && confirming === index}
                  onClick={() => remove(index)}
                >
                  {confirming === index ? "Remove its lines too" : "Remove"}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      <div style={{ fontSize: 12, fontWeight: 700, margin: "14px 0 6px" }}>
        Add a section
      </div>
      <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
        {addableKinds(content).map((kind) => (
          <button
            key={kind}
            type="button"
            className="chip-add"
            disabled={busy || filling !== null}
            onClick={() => onAdd({ kind, title: null })}
          >
            + {SECTION_HEADINGS[kind]}
          </button>
        ))}
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
            onAdd({ kind: "custom", title });
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
        New sections are filled from your sources; add or edit lines in place.
      </p>
    </div>
  );
}
