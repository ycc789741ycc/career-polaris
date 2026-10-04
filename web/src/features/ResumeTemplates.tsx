import { useRef, useState } from "react";
import { api } from "../api/client";
import type {
  ResumeTemplateLimits,
  ResumeTemplateLook,
  ResumeTemplateSpec,
  TemplateField,
  TemplateReading,
} from "../api/types";
import {
  Button,
  ErrorNote,
  Eyebrow,
  Field,
  RoundCheck,
} from "../components/ui";
import { messageOf } from "./useAsync";

/** The list sections a sidebar may hold, as the server checks them. */
const SIDEBAR_KINDS: {
  kind: ResumeTemplateSpec["sidebar_kinds"][number];
  label: string;
}[] = [
  { kind: "skills", label: "Skills" },
  { kind: "certifications", label: "Certifications" },
];

const LAYOUTS: { value: ResumeTemplateSpec["layout"]; label: string }[] = [
  { value: "single_column", label: "One column" },
  { value: "header_band", label: "One column, tinted header" },
  { value: "sidebar_left", label: "Sidebar on the left" },
  { value: "sidebar_right", label: "Sidebar on the right" },
];

const COLORS: { key: ColorKey; label: string }[] = [
  { key: "accent_color", label: "Accent — bullets and the band" },
  { key: "name_color", label: "Name and headings" },
  { key: "text_color", label: "Text" },
  { key: "rule_color", label: "Line under the header" },
];

const SIZES: { key: SizeKey; label: string; range: RangeKey }[] = [
  { key: "name_pt", label: "Name", range: "name_pt_range" },
  { key: "heading_pt", label: "Headings", range: "heading_pt_range" },
  { key: "body_pt", label: "Body", range: "body_pt_range" },
];

const POLL_MS = 1500;

const LAYOUT_PHRASES: Record<ResumeTemplateSpec["layout"], string> = {
  single_column: "one column",
  header_band: "one column under a tinted header",
  sidebar_left: "a left sidebar",
  sidebar_right: "a right sidebar",
};

const FONT_PHRASES: Record<ResumeTemplateSpec["heading_font"], string> = {
  Caprasimo: "a display",
  Figtree: "a sans-serif",
  "DejaVu Serif": "a serif",
  "DejaVu Sans Mono": "a monospaced",
  Inter: "a sans-serif",
  Lato: "a sans-serif",
  "Source Serif 4": "a serif",
  Merriweather: "a serif",
  "EB Garamond": "a serif",
  "IBM Plex Mono": "a monospaced",
};

/** What a reading found, in a sentence: "We read: a left sidebar, a serif
 * heading, its accent colour and its type sizes." Pure. */
export function describeReading(
  spec: ResumeTemplateSpec,
  read: TemplateField[],
): string {
  const has = (field: TemplateField) => read.includes(field);
  const parts = [
    has("layout") ? LAYOUT_PHRASES[spec.layout] : null,
    has("heading_font") ? `${FONT_PHRASES[spec.heading_font]} name` : null,
    has("body_font") ? `${FONT_PHRASES[spec.body_font]} text face` : null,
    has("accent_color") ? "its accent colour" : null,
    has("name_pt") || has("body_pt") ? "its type sizes" : null,
    has("bullet") ? "its bullets" : null,
  ].filter((part): part is string => part !== null);
  if (parts.length === 0) return "We could read little from it.";
  const last = parts.pop()!;
  return `We read: ${parts.length ? `${parts.join(", ")} and ${last}` : last}.`;
}

type ColorKey = "accent_color" | "name_color" | "text_color" | "rule_color";
type SizeKey = "name_pt" | "heading_pt" | "body_pt";
type RangeKey = "name_pt_range" | "heading_pt_range" | "body_pt_range";

/** The WCAG contrast ratio of a #rrggbb colour on the white page. Pure. */
export function getContrast(color: string, background = "#ffffff"): number {
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
  };
  const [light, dark] = [luminance(color), luminance(background)].sort(
    (a, b) => b - a,
  );
  return (light! + 0.05) / (dark! + 0.05);
}

/** Why a spec would be refused, in the server's terms, or null. The server
 * checks it again; this only says so before the round trip. Pure. */
export function specProblem(
  name: string,
  spec: ResumeTemplateSpec,
  limits: ResumeTemplateLimits,
): string | null {
  if (!name.trim()) return "Give the template a name.";
  if (name.trim().length > limits.max_name)
    return `A name has at most ${limits.max_name} characters.`;
  for (const { key, label } of COLORS) {
    if (!/^#[0-9a-f]{6}$/i.test(spec[key])) return `${label}: pick a colour.`;
  }
  for (const key of ["name_color", "text_color"] as const) {
    if (getContrast(spec[key]) < limits.min_contrast)
      return `${key === "name_color" ? "The name" : "The text"} is too light to read on a white page.`;
  }
  for (const { key, label, range } of SIZES) {
    const [low, high] = limits[range];
    if (spec[key] < low || spec[key] > high)
      return `${label} size is from ${low} to ${high}pt.`;
  }
  return null;
}

/** A template's look with a spec being edited: the derived sizes, the rule
 * and the band worked out as the renderer does, so the page previews it
 * live. Pure. */
export function withSpec(
  look: ResumeTemplateLook,
  spec: ResumeTemplateSpec,
): ResumeTemplateLook {
  const widths = { none: "0", thin: "1px", thick: "3px" } as const;
  const band =
    "#" +
    [1, 3, 5]
      .map((i) => parseInt(spec.accent_color.slice(i, i + 2), 16))
      .map((c) =>
        Math.round(255 - (255 - c) / 8)
          .toString(16)
          .padStart(2, "0"),
      )
      .join("");
  return {
    ...look,
    spec,
    rule: `${widths[spec.rule]} solid ${spec.rule_color}`,
    band_color: band,
    title_pt: spec.body_pt + 1,
    contact_pt: spec.body_pt - 0.5,
    small_pt: spec.body_pt - 1,
  };
}

/**
 * "Make your own": a template as checked values, never markup (ADR 0040).
 * Each change previews on the page at once; Save keeps it, for every résumé.
 */
export function TemplateEditor({
  limits,
  from,
  editing,
  onPreview,
  onSaved,
  onDeleted,
  onClose,
}: {
  limits: ResumeTemplateLimits;
  /** The template it starts from: the one being edited, or the one picked. */
  from: ResumeTemplateLook;
  /** True when changing a template of the user's own; false makes a new one. */
  editing: boolean;
  /** The spec as it stands, for the page to preview. */
  onPreview: (spec: ResumeTemplateSpec) => void;
  onSaved: (template: ResumeTemplateLook) => void;
  onDeleted: (id: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(editing ? from.name : `${from.name} — mine`);
  const [spec, setSpec] = useState<ResumeTemplateSpec>(from.spec);
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What a file's reading found, once the editor opens on its draft.
  const [fromFile, setFromFile] = useState<TemplateReading | null>(null);
  const [reading, setReading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const problem = specProblem(name, spec, limits);
  /** A label, marked when the value was read from the file or defaulted. */
  const marked = (label: string, ...fields: TemplateField[]) => {
    if (!fromFile) return label;
    if (fields.some((f) => fromFile.defaulted.includes(f)))
      return `${label} — not read; Organic's, check it`;
    return `${label} — read from the file`;
  };

  async function startFromFile(file: File | null) {
    if (!file) return;
    setError(null);
    if (file.size > limits.upload_max_bytes) {
      setError(
        `That file is over ${Math.round(limits.upload_max_bytes / 1_048_576)} MB.`,
      );
      return;
    }
    setReading(true);
    try {
      let job = await api.upload<TemplateReading>(
        "/resume-templates/upload",
        file,
      );
      while (job.status === "reading") {
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        job = await api.get<TemplateReading>(
          `/resume-template-readings/${job.id}`,
        );
      }
      if (job.status === "failed" || !job.spec) {
        setError(job.error?.message ?? "That file could not be read.");
        return;
      }
      setFromFile(job);
      setName("From a file");
      change(job.spec);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setReading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }
  const hasSidebar =
    spec.layout === "sidebar_left" || spec.layout === "sidebar_right";

  function change(patch: Partial<ResumeTemplateSpec>) {
    const next = { ...spec, ...patch };
    setSpec(next);
    onPreview(next);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = { name: name.trim(), spec };
      const saved = editing
        ? await api.put<ResumeTemplateLook>(
            `/resume-templates/${from.id}`,
            body,
          )
        : await api.post<ResumeTemplateLook>("/resume-templates", body);
      onSaved(saved);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    setError(null);
    try {
      await api.del(`/resume-templates/${from.id}`);
      onDeleted(from.id);
    } catch (caught) {
      setError(messageOf(caught));
      setSaving(false);
    }
  }

  return (
    <div
      className="template-editor"
      role="group"
      aria-label={editing ? "Change your template" : "Make your own"}
      style={{ marginTop: 16 }}
    >
      <Eyebrow style={{ marginBottom: 12 }}>
        {editing ? "Change your template" : "Make your own"}
      </Eyebrow>
      {!editing && (
        <div className="stack" style={{ gap: 8, marginBottom: 14 }}>
          <p className="subcopy" style={{ fontSize: 12.5, margin: 0 }}>
            Start from a PDF of a résumé whose look you like. We read its style
            only — layout, fonts, colours, sizes — never its words, and delete
            the file once it is read. A very designed page, with photos, icons
            or three columns, comes out as the nearest of four layouts.
          </p>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            aria-label="Résumé PDF to start from"
            style={{ display: "none" }}
            onChange={(event) =>
              void startFromFile(event.target.files?.[0] ?? null)
            }
          />
          <Button
            variant="secondary"
            busy={reading}
            onClick={() => fileInput.current?.click()}
          >
            {reading ? "Reading its style…" : "Start from a file"}
          </Button>
          {fromFile?.spec && (
            <p className="resume-annotation" role="status">
              {describeReading(fromFile.spec, fromFile.read)} Anything marked
              “not read” is Organic’s — check it before you save.
            </p>
          )}
        </div>
      )}
      <Field label="Name">
        <input
          className="input"
          value={name}
          maxLength={limits.max_name}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>
      <Field label={marked("Layout", "layout")}>
        <select
          className="input"
          value={spec.layout}
          onChange={(event) =>
            change({
              layout: event.target.value as ResumeTemplateSpec["layout"],
            })
          }
        >
          {LAYOUTS.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </Field>
      {hasSidebar && (
        <div className="stack" style={{ gap: 8, marginBottom: 14 }}>
          <span className="field-label">In the sidebar</span>
          <p className="subcopy" style={{ fontSize: 12.5, margin: 0 }}>
            Some applicant-tracking systems read a sidebar out of order. One
            column is the safer choice for a form that parses your résumé.
          </p>
          {SIDEBAR_KINDS.map(({ kind, label }) => (
            <RoundCheck
              key={kind}
              checked={spec.sidebar_kinds.includes(kind)}
              onChange={(on) =>
                change({
                  sidebar_kinds: on
                    ? [...spec.sidebar_kinds, kind]
                    : spec.sidebar_kinds.filter((k) => k !== kind),
                })
              }
            >
              {label}
            </RoundCheck>
          ))}
        </div>
      )}
      {(["heading_font", "body_font"] as const).map((key) => (
        <Field
          key={key}
          label={marked(
            key === "heading_font" ? "Name and titles in" : "Text in",
            key,
          )}
        >
          <select
            className="input"
            value={spec[key]}
            onChange={(event) =>
              change({
                [key]: event.target.value as ResumeTemplateSpec["heading_font"],
              })
            }
          >
            {limits.fonts.map((font) => (
              <option key={font} value={font}>
                {font}
              </option>
            ))}
          </select>
        </Field>
      ))}
      {COLORS.map(({ key, label }) => (
        <Field key={key} label={marked(label, key)}>
          <input
            className="input template-color"
            type="color"
            value={spec[key]}
            onChange={(event) => change({ [key]: event.target.value })}
          />
        </Field>
      ))}
      <Field label={marked("Line under the header", "rule")}>
        <select
          className="input"
          value={spec.rule}
          onChange={(event) =>
            change({ rule: event.target.value as ResumeTemplateSpec["rule"] })
          }
        >
          <option value="thick">Thick</option>
          <option value="thin">Thin</option>
          <option value="none">None</option>
        </select>
      </Field>
      {SIZES.map(({ key, label, range }) => (
        <Field key={key} label={marked(`${label} size — ${spec[key]}pt`, key)}>
          <input
            type="range"
            style={{ width: "100%" }}
            min={limits[range][0]}
            max={limits[range][1]}
            step={0.5}
            value={spec[key]}
            onChange={(event) => change({ [key]: Number(event.target.value) })}
          />
        </Field>
      ))}
      <Field label={marked("Headings", "heading_case")}>
        <select
          className="input"
          value={spec.heading_case}
          onChange={(event) =>
            change({
              heading_case: event.target
                .value as ResumeTemplateSpec["heading_case"],
            })
          }
        >
          <option value="upper">IN CAPITALS</option>
          <option value="as_written">As written</option>
        </select>
      </Field>
      <Field label={marked("Bullets", "bullet")}>
        <select
          className="input"
          value={spec.bullet}
          onChange={(event) =>
            change({
              bullet: event.target.value as ResumeTemplateSpec["bullet"],
            })
          }
        >
          <option value="dot">Dots</option>
          <option value="dash">Dashes</option>
          <option value="none">None</option>
        </select>
      </Field>
      {(problem ?? error) && <ErrorNote error={(problem ?? error)!} />}
      <div className="row" style={{ gap: 8 }}>
        <Button
          busy={saving}
          disabled={problem !== null}
          onClick={() => void save()}
        >
          {editing ? "Save changes" : "Save template"}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      </div>
      {editing &&
        (confirming ? (
          <div className="stack" style={{ gap: 8 }}>
            <p className="subcopy" style={{ fontSize: 12.5 }}>
              Résumés set in it go back to Organic. PDFs already downloaded stay
              as they are.
            </p>
            <div className="row" style={{ gap: 8 }}>
              <Button
                variant="ghost"
                busy={saving}
                onClick={() => void remove()}
              >
                Delete it
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                Keep it
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="ghost" onClick={() => setConfirming(true)}>
            Delete this template
          </Button>
        ))}
    </div>
  );
}
