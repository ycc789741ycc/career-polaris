# Career Advisor — Domain Concepts & Design Decisions

This summarizes the design review of the "Career Advisor — current layout" canvas (28 Sep 2026). Use it as the spec when revising the code. Sample data (Maya Chen, Northwind Pay, etc.) is illustrative only.

## 1. User journey (forward-only)

```
01 Sources ──► 02 Strengths ──► 03 Role map ──► 04 Advisor
 (profile)      (analysis)       (market)        First: Fill the gap
                                                 Then, either: Gap plan | Résumé
```

- A step reads only from the steps before it, never from later ones. For example, Strengths shows no role fit; comparing against roles is the Role map's job.
- The one exception is a deliberate feedback loop: answers given in **Fill the gap** are written back into **Sources** as evidence (see §5).

## 2. Core entities

| Entity | Description | Key fields |
|---|---|---|
| **User profile** | Owner of all data | name, contact, **target locations (1–3)**, model setting |
| **Target location** | Where the user wants to work. Chosen in the profile (01 Sources). **Max 3.** Scopes the market search and salary bands. | name (city / country / remote region e.g. "Remote EU") |
| **Source** | An evidence provider | type: `github` \| `jira` \| `resume` \| `user_answer`; status (connected / not connected / parsed); last synced |
| **Fact (evidence)** | One traceable piece of evidence | source, source ref (e.g. `payments-api#1284`), text |
| **Strength dimension** | A scored skill axis (e.g. Backend systems, Incident response, Tech leadership…) | score 0–100, **confidence %**, cited facts |
| **Profile confidence** | How well the evidence supports the strength scores overall | percentage |
| **Role (market)** | A role found on the market or added by the user | title, company?, JD?, fit %, salary band, hiring bar, openings, origin: `recommended` \| `custom` |
| **Target role** | The single role the Advisor works against | a reference to one Role (+ company/opening) |
| **Gap** | A requirement of the target role that the evidence doesn't fully cover | title, status: `partial` \| `no_evidence`, fit-point impact |
| **Follow-up question** | Generated per gap to collect missing evidence | gap, question text, "asked because" reason, answer type (choice / free text), answer |
| **Gap plan** | Plan to close the gaps to the target role | gaps ranked by fit impact, milestones & tasks, stepping-stone roles, projects |
| **Résumé** | A tailored résumé for the target role | versions, template, requirement → evidence coverage (Covered / Partial / Gap) |

## 3. 01 Sources (Profile)

- **Target locations**: chips with remove buttons, an input with Add, and a counter ("2 of 3 chosen"). A hard cap of 3: once 3 are chosen, the user must remove one before adding another.
- Source connectors: GitHub, Jira, existing résumé (upload PDF/DOCX → "Analyze with AI").
- "What it found so far": a breakdown of facts by source (GitHub / Résumé / **Your answers**).
- Evidence table, filterable by source.
- **Removed:** the "Fill the gaps" follow-up questions block. Questions no longer live on Sources.
- **Removed:** the Profile confidence meter from the shared sidebar (it moved to Strengths).
- Sidebar: no badge count on Sources.

## 4. 02 Strengths (Analysis)

- Skill radar across dimensions; the list is ordered "least certain first".
- Each dimension shows its **score** and a separate **confidence** (how sure the score is), plus cited evidence.
- **Profile confidence** lives here, next to Re-analyse. It means how well the evidence backs the strength scores, so it belongs to the analysis stage, not to Sources.
- The thin-evidence hint points to Sources ("Connect more sources, like Jira, to add more").

## 5. 03 Role map (Market)

- **Built automatically after the strength analysis.** A background worker searches the market for the best-fit roles. **Default: 10 roles, decided by the system** (not user-configurable).
- The search is scoped to the user's **target locations** (e.g. "1,284 open postings in Berlin and Remote EU").
- Bubble chart: x = hiring bar, y = salary midpoint, size = fit. A dashed outline means the hiring bar is an AI estimate.
- **Custom role**: if the user isn't satisfied with the recommendations, they add their own role:
  - Job title (**required**)
  - Company name (optional)
  - JD (optional; improves the analysis; private to the user)
  - The **"Add to Role Map"** button triggers the analysis and places the role on the map.
  - Custom roles are visually distinct (green outline, "yours" label).
- Top matched openings list (no subscribe action).
- **Exactly one control aims the Advisor:** the sticky "Advisor target" bar → "Target this role", which opens Fill the gap.
- **Removed:** Subscribe buttons, "Roles to watch", "Roles to analyse" (count input), "Markets you are looking in" (replaced by profile target locations), and the market filter pills.

## 6. 04 Advisor

The Advisor always works against **one target role**, already chosen on the Role map.

- **No role or company picker inside the Advisor.** Changing role means going back to the Role map ("Change role" link).
- Every Advisor page opens with an explicit **"Your target role" banner**: the title, "at {company} · {location} · {posting}", fit today, salary band, and "Everything on this page is measured against this one role."
- Navigation is a fork, not a linear sequence:
  **First:** Fill the gap → **Then, either:** Gap plan | Résumé

### 6.1 Fill the gap (first step)

- The system compares the user's evidence against the target role's requirements and generates **follow-up questions per gap**.
- Gaps are grouped as cards: title, status tag (Partial / No evidence), and potential fit points.
- Each question has an "Asked because: …" reason and an answer input (choice buttons and/or free text).
- **A single "Submit answers" button** (with an answered count, e.g. "4 of 5 answered", and a cost estimate on the user's key).
- **On submit:**
  1. Each answer becomes a **Fact** in Sources with source type `user_answer` ("Your answers").
  2. The Gap plan and Résumé are regenerated or updated from the new evidence.
- Answers are **not** auto-saved per question. Nothing propagates until the user submits.
- Unanswered questions stay gaps.

### 6.2 Gap plan

- Gaps between the user and the target role, ranked by fit impact, each citing evidence.
- Milestones & tasks with progress, stepping-stone roles, and "projects that prove it".
- Notes that it uses the answers from Fill the gap.

### 6.3 Résumé

- Tailored to the target role; saved versions per company; templates; PDF export.
- A requirements → evidence panel (Covered / Partial / Gap).
- AI revise chat; proposals apply only on user confirmation.
- Drafted from sources, including the Fill the gap answers.

## 7. Cross-cutting rules

- Every AI action shows a cost estimate on the user's own API key before running.
- Every claim or score must be traceable to a Fact and its source ref.
- "No evidence" is distinct from a low score: nothing speaks to it either way.
- The model in use (e.g. `claude-sonnet-5`) is shown and configured under System configuration → AI & model.

## 8. Data flow summary

```
Target locations ─┐
                  ▼
Sources ─► Facts ─► Strength analysis (scores, confidence, profile confidence)
  ▲                         │
  │                         ▼
  │              Role map worker (top 10 fit roles in target locations)
  │                 + custom roles ("Add to Role Map")
  │                         │ user picks one → Target role
  │                         ▼
  │              Fill the gap: generate questions per gap
  │                         │ Submit answers
  └──── user_answer facts ◄─┤
                            ▼
                 Gap plan  |  Résumé   (regenerated from updated facts)
```
