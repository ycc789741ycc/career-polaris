# Career Advisor — design prototypes

Exported from the "Career Advisor — current layout" design canvas (28 Sep 2026).
These files are the **design reference** for the UI. Match their layout, copy and behaviour; don't ship them as-is.

## Contents

| File | Screen |
|---|---|
| `screens/Main.dc.html` | 01 Sources (profile: target locations, source connectors, evidence) |
| `screens/Strengths.dc.html` | 02 Strengths (radar, per-dimension confidence, profile confidence) |
| `screens/Roles.dc.html` | 03 Role map (top-10 fit roles, custom "Add to Role Map", Advisor target bar) |
| `screens/Gaps.dc.html` | 04 Advisor: Fill the gap (follow-up questions + Submit answers) |
| `screens/Plan.dc.html` | 04 Advisor: Gap plan |
| `screens/Resume.dc.html` | 04 Advisor: Résumé |
| `screens/Model.dc.html` | System configuration: AI & model |
| `screens/Sidebar.dc.html` | Shared sidebar nav component |
| `canvas.json` | Board index: titles, order, sizes, and the design-rules sticky note |
| `career-advisor-domain-spec.md` | Domain model, flow and decisions. **Read this first.** |

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
- Accent terracotta `#c67139` (primary buttons), deep `#8c491a` / `#643312`, highlight `#ffe1d0`.
- Green positive `#56633f`, green surface `#e1eecc` (text on it: `#3d472b`).
- Radius: cards 28px, inner panels 16px, pills 999px.
