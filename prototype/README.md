# Career Advisor — design prototypes

Exported from the "Career Advisor — current layout" design canvas (3 Oct 2026).
These files are the **design reference** for the UI. Match their layout, copy and behaviour; don't ship them as-is.

## Contents

| File | Screen |
|---|---|
| `screens/Main.dc.html` | 01 Sources (profile: target locations, source connectors, evidence) |
| `screens/StrengthsBuilding.dc.html` | 02 Strengths — analysing (waiting screen) |
| `screens/Strengths.dc.html` | 02 Strengths (radar, per-dimension confidence, profile confidence, Re-analyse) |
| `screens/RolesBuilding.dc.html` | 03 Role map — building (waiting screen) |
| `screens/Roles.dc.html` | 03 Role map (Rebuild, top-10 market map, Selected role fit card, Advisor target bar) |
| `screens/CustomTarget.dc.html` | 04 Advisor — Your own role (upload JD or fill in, My roles list) |
| `screens/Gaps.dc.html` | 04 Advisor — Fill the gap (follow-up questions + Submit answers) |
| `screens/Plan.dc.html` | 04 Advisor — Gap plan |
| `screens/Resume.dc.html` | 04 Advisor — Résumé |
| `screens/Model.dc.html` | System configuration: AI & model |
| `screens/Sidebar.dc.html` | Shared sidebar nav component |
| `canvas.json` | Board index: titles, order, sizes, and the design-rules sticky note |
| `career-advisor-domain-spec.md` | Domain model, flow and decisions. **Read this first.** |

## Click-through flow

Sources → "Analyze with AI" → Strengths (analysing) → Strengths → "Match me to roles" → Role map (building) → Role map → "Target this role" → Fill the gap → Gap plan | Résumé.
From any Advisor page: "Use your own role" → Your own role → "Set as target" → Fill the gap.

## How to read a `.dc.html` file

- Each file is one screen at a fixed desktop width (1440px). Styles are inline.
- `<x-dc> … </x-dc>` holds the markup. `<helmet>` holds fonts and base CSS.
- `<dc-import name="Sidebar" current="sources">` embeds the shared `Sidebar.dc.html` component with a prop.
- `{{name}}`, `<sc-for list=…>` and `<sc-if value=…>` are template bindings. Their data comes from `renderVals()` in the `<script type="text/x-dc">` block at the bottom.
- `./support.js` is the design tool's runtime and **is not included**. The files won't render standalone, so treat them as a source reference.
- Links like `href="Gaps.dc.html"` show navigation between screens.
- All names, companies, numbers and facts are **sample data**.

## Design tokens (Organic look)

- Fonts: **Caprasimo** (display), **Figtree** (body), both from Google Fonts.
- Background `#f5ead8`, card `#ebddc5`, text `#201e1d`, muted text `#474238` / `#645c50`.
- Accent terracotta `#c67139` (primary buttons), deep `#8c491a` / `#643312`, highlight `#ffe1d0`, bar fill `#b2622d`.
- Green positive `#56633f`, green surface `#e1eecc` (text on it: `#3d472b`). Track `#dcd3c4`.
- Radius: cards 28px, inner panels 16px, pills 999px.
