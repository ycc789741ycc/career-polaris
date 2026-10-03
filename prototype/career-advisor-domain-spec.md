# Career Advisor — Domain Concepts & Design Decisions

This summarizes the design review of the "Career Advisor — current layout" canvas (last updated 3 Oct 2026, evening). Use it as the spec when revising the code. Sample data (Maya Chen, Northwind Pay, etc.) is illustrative only.

## 1. User journey (forward-only)

```
01 Sources ──► [analysing] ──► 02 Strengths ──► [building] ──► 03 Role map ──► 04 Advisor
 (profile)     waiting screen   (analysis)      waiting screen   (market)       target: role map pick OR own role
                                                                                First: Fill the gap
                                                                                Then, either: Gap plan | Résumé
```

- A step reads only from the steps before it, never from later ones. For example, Strengths shows no role fit; comparing against roles is the Role map's job.
- The one exception is a deliberate feedback loop: answers given in **Fill the gap** are written back into **Sources** as evidence (see §6.1).
- The role map build starts **automatically** when the strength analysis finishes.

## 2. Core entities

| Entity | Description | Key fields |
|---|---|---|
| **User profile** | Owner of all data | name, contact, **target locations (1–3)**, model setting |
| **Target location** | Where the user wants to work. Chosen in the profile (01 Sources). **Max 3.** Scopes the market search and salary bands. | name (city / country / remote region e.g. "Remote EU") |
| **Source** | An evidence provider | type: `github` \| `jira` \| `resume` \| `user_answer`; status (connected / not connected / parsed); last synced |
| **Fact (evidence)** | One traceable piece of evidence | source, source ref (e.g. `payments-api#1284`), text |
| **Strength dimension** | A scored skill axis (e.g. Backend systems, Incident response) | score 0–100, **confidence %**, cited facts |
| **Profile confidence** | How well the evidence supports the strength scores overall | percentage |
| **Analysis run / Role map run** | A background job with visible progress | status, steps (done / running / waiting), progress %, ETA, cost estimate, cancellable |
| **Market role** | A role found by the role map worker (system only) | title, fit %, annual pay band, hiring bar (reported or AI estimate), openings, per-dimension requirement levels |
| **Own role (custom role)** | A role the user brings themselves, **never shown on the role map** | job title (required), company?, requirements? (or parsed from an uploaded JD file), source: `uploaded_jd` \| `filled_in`, added date |
| **Target role** | The single role the Advisor works against | reference to a Market role (+ opening) **or** an Own role |
| **Gap** | A requirement of the target role that the evidence doesn't fully cover | title, status: `partial` \| `no_evidence`, fit-point impact |
| **Follow-up question** | Generated per gap to collect missing evidence | gap, question text, "asked because" reason, answer type (choice / free text), answer |
| **Gap plan** | Plan to close the gaps to the target role | gaps ranked by fit impact, milestones & tasks, stepping-stone roles, projects |
| **Résumé** | A tailored résumé for the target role | versions, template, **sections** (ordered, removable; Experience required), requirement → evidence coverage (Covered / Partial / Gap) |
| **Advisor job** | A short AI run inside the Advisor (questions, gap plan, résumé) | type, target role, progress %, cost estimate, status; runs in the background while the user keeps working |

## 3. 01 Sources (Profile)

- **Target locations**: chips with remove buttons, an input with Add, and a counter ("2 of 3 chosen"). A hard cap of 3: once 3 are chosen, the user must remove one before adding another.
- Source connectors: GitHub, Jira, existing résumé (upload PDF/DOCX → **"Analyze with AI" opens the analysing waiting screen**).
- "What it found so far": a breakdown of facts by source (GitHub / Résumé / **Your answers**).
- Evidence table, filterable by source.
- No follow-up questions here (they live in the Advisor's Fill the gap). No profile confidence here (it lives on Strengths).

## 4. 02 Strengths (Analysis)

- **Waiting screen ("analysing")** while the run is in progress: overall % and time left, steps (Collected facts → Grouped by skill → Scoring each dimension → Checking confidence → Writing report), a radar that fills in point by point, "you don't need to wait here" (the role map builds automatically afterwards), cost (~12 calls), Cancel run.
- Result: skill radar; list ordered "least certain first".
- Each dimension shows its **score** and a separate **confidence**, plus cited evidence.
- **Profile confidence** sits next to **Re-analyse**, with the last-run line ("Analysed {date} on {model} · {n} facts read").
- The thin-evidence hint points to Sources ("Connect more sources, like Jira, to add more").
- "Match me to roles" opens the role map waiting screen.

## 5. 03 Role map (Market)

- **Built automatically after the strength analysis** by a background worker. **Default: 10 roles, decided by the system** (not user-configurable). Only system-found roles appear here.
- **Waiting screen ("building")**: overall % and time left, steps (Read strength analysis → Searched postings in your locations → Scoring fit → Picking 10 best-fit roles → Drawing the map), an empty map preview, "you don't need to wait here", cost (~40 calls), Cancel run.
- **Toolbar**, laid out like Strengths: **"Rebuild role map"** button + "Built {date} on {model} · {n} open postings in {locations} · about 40 calls to rebuild".
- Bubble chart: x = hiring bar, y = salary midpoint, size = fit. A dashed outline means the hiring bar is an AI estimate.
- **Selected role card:**
  - Title; stats: **Fit**, **Annual pay**, **Openings**, each with a context line (e.g. "across 38 postings", locations).
  - A one-line verdict ("You clear 3 of 6 skills this role screens for") plus 1–2 plain sentences. **Use display names, never internal slugs** (no `backend-eng-python`).
  - **"How you fit each skill"**, sorted biggest gap first. Each row: name, "you X · asks Y", a signed gap chip (−23 terracotta / +14 green). Bar = track; fill = your score (terracotta if below the target, green if you meet it); hatched segment from your score to the target = shortfall; 3px dark tick at the target. Legend above the rows. Each bar has an aria-label ("{skill}: you X, role asks Y").
  - "What this role asks for" (collapsible).
  - No "no evidence" callout on this card.
- Top matched openings list (no subscribe action).
- Sticky "Advisor target" bar → "Target this role" opens Fill the gap.
- **Removed:** custom role entry ("Add to Role Map"), Subscribe buttons, "Roles to watch", "Roles to analyse", "Markets you are looking in", market filter pills.

## 6. 04 Advisor

The Advisor always works against **one target role**.

- Every Advisor page opens with a **"Your target role" banner**: title, "at {company} · {location} · {posting}", fit today, salary band, "Everything on this page is measured against this one role", and two buttons: **"Pick from role map"** and **"Use your own role"**.
- No company/opening picker inside the Advisor pages.
- Navigation is a fork, not a linear sequence:
  **First:** Fill the gap → **Then, either:** Gap plan | Résumé

### 6.0 Your own role (custom target)

- One **"Your role"** block with two ways side by side ("One is enough"):
  - **Upload the job description**: file drop zone only (PDF, DOCX, TXT).
  - **Fill it in yourself**: Job title (required), Company (optional), "What the role asks for" (optional, one per line; if empty the Advisor infers typical requirements and marks them as estimates).
  - **"Add to my roles"** saves the role to the list. Adding does **not** run any analysis.
- **"My roles" list**: each role shows how it was added (uploaded JD / filled in) and the date, with **"Set as target"** and **"Remove"**.
  - "Set as target" compares the role with the user's strengths and generates the gap questions (cost shown first, ~6 calls), replaces the current target, and opens Fill the gap.
- Own roles never go to the role map or its analysis.

### 6.1 Fill the gap (first step)

- The system compares the user's evidence against the target role's requirements and generates **follow-up questions per gap**.
- Gaps are grouped as cards: title, status tag (Partial / No evidence), and potential fit points.
- Each question has an "Asked because: …" reason and an answer input (choice buttons and/or free text).
- **A single "Submit answers" button** (with an answered count and a cost estimate).
- **On submit:** each answer becomes a **Fact** in Sources (`user_answer`), and the Gap plan and Résumé are regenerated from the new evidence.
- Answers are **not** auto-saved per question. Unanswered questions stay gaps.

### 6.2 Gap plan

- "Generate gap plan" / "regenerate" start a drafting job (cost shown; saved as a new version, older versions kept in Plan history).
- Gaps ranked by fit impact. Each gap row: title, "+N fit pts" **and a bar** (points out of 10), a one-line reason, and a collapsed **"Show evidence (n)"**: cited evidence is hidden until expanded.
- Milestones & tasks with progress; stepping-stone roles; projects that prove it.
- Notes that it uses the answers from Fill the gap.

### 6.3 Résumé

- "Write for" card with **"Regenerate résumé"** (cost shown; saved as a new version, older versions kept in Saved résumés).
- Left column, top to bottom: Saved résumés → Template (+ Export PDF) → **Sections** → **Revise with AI**.
- **Sections panel**: lists the résumé's blocks in order (Summary, Experience, Skills, Side projects…), each with a drag handle and Remove; Experience is required. "Add a section" offers Education, Talks & writing, Open source, Certifications, Custom… New sections are filled from the user's sources and editable in place.
- Résumé preview in the middle; lines are edited in place; "Save as vN".
- Right column: requirements → evidence panel. Each row shows only status (Covered / Partial / Gap) and the requirement; **evidence is collapsed** behind "Evidence ▾".
- AI revise chat: proposals apply only on user confirmation.

### 6.4 Advisor jobs (generating states)

- Generating follow-up questions, a gap plan or a résumé are short jobs (under a minute) and **do not block the Advisor**.
- While a job runs, its page keeps the target banner and step tabs; the content area shows a slim progress card (spinner, title, one status line, progress bar, cost, Cancel) with links to the other tabs.
- The tab being generated shows a spinner and a word (preparing… / drafting… / writing…) until it is done, wherever the user is.
- The user can switch tabs and keep working (e.g. edit the Gap plan while the résumé is written); a small notice in the corner shows the running job ("Writing your résumé · 50% · View").
- Entry points: "Target this role" / "Set as target" → questions job; "Generate gap plan" / "regenerate" → plan job; "Regenerate résumé" → résumé job.

## 7. Cross-cutting rules

- Every AI action shows a cost estimate on the user's own API key before running.
- Long AI jobs (strength analysis, role map build) show a full waiting screen with steps, progress, ETA, cost and Cancel; the user can leave and the job keeps running.
- Short Advisor jobs run in the background with an inline progress card and a spinner on their tab (§6.4).
- Evidence is detail: show it collapsed, expanded on demand.
- Every claim or score must be traceable to a Fact and its source ref.
- "No evidence" is distinct from a low score.
- The model in use (e.g. `claude-sonnet-5`) is shown and configured under System configuration → AI & model.

## 8. Data flow summary

```
Target locations ─┐
                  ▼
Sources ─► Facts ─► Strength analysis run (scores, confidence, profile confidence)
  ▲                         │ auto-starts
  │                         ▼
  │              Role map run (top 10 fit roles in target locations)   ◄── Rebuild
  │                         │ "Target this role"
  │                         ▼
  │                   Target role  ◄── "Set as target" ◄── My roles (uploaded JD / filled in)
  │                         │
  │                         ▼
  │              Fill the gap: questions per gap
  │                         │ Submit answers
  └──── user_answer facts ◄─┤
                            ▼
                 Gap plan  |  Résumé   (regenerated from updated facts)
```
