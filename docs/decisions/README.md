# Decision records

Decisions that are costly to reverse or non-obvious to the next reader. An
accepted record is immutable apart from its status line: a changed mind is a
new record that supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [0001](0001-run-our-own-email-password-sign-in.md) | Run our own email-and-password sign-in instead of a hosted provider | Accepted |
| [0002](0002-analyse-only-the-ten-closest-roles.md) | Analyse only the ten roles closest to the user's profile | Superseded by 0003 |
| [0003](0003-let-the-user-choose-how-many-roles-to-analyse.md) | Let the user choose how many roles to analyse (3–20, default 10) | Superseded by 0020 |
| [0004](0004-build-the-spa-on-the-prototypes-design-system.md) | Build the SPA on the prototype's design system and sidebar shell | Accepted |
| [0005](0005-resolve-targets-in-their-own-module.md) | Resolve Targets in their own module | Accepted, amended by 0022 and 0033 |
| [0006](0006-report-ai-job-progress-through-a-status-the-page-polls.md) | Report AI job progress through a status the page polls | Accepted |
| [0007](0007-render-resume-pdfs-with-weasyprint.md) | Render résumé PDFs with WeasyPrint, not a headless browser | Accepted |
| [0008](0008-sign-in-with-google-by-our-own-oidc-exchange.md) | Sign in with Google through our own OpenID Connect exchange, and let a verified address take over an unverified one | Accepted |
| [0009](0009-package-the-backend-by-component.md) | Package the backend by component, keeping `kernel/` outside the application | Accepted |
| [0010](0010-define-repositories-in-the-domain-in-domain-types.md) | Define repositories in the domain, in domain types | Superseded by 0011 |
| [0011](0011-give-every-repository-the-same-six-methods.md) | Give every repository the same six methods, a filter and a factory | Accepted |
| [0012](0012-generate-follow-up-questions-when-evidence-changes.md) | Generate follow-up questions in the background when evidence changes | Superseded by 0023 |
| [0013](0013-type-every-http-response-with-a-schema-model.md) | Type every HTTP response with a schema model built from a component's view | Accepted |
| [0014](0014-page-every-list-response.md) | Page every list response, with `page`, `page_size` and `total` | Accepted |
| [0015](0015-remove-a-resumes-evidence-with-it-and-flag-reports-it-outdates.md) | Remove a résumé's evidence with it, and mark every report the profile has moved past as out of date | Accepted |
| [0016](0016-count-github-work-by-commit-not-pull-request.md) | Count GitHub work by commit, not by pull request | Accepted |
| [0017](0017-group-jira-work-by-epic-not-project.md) | Group Jira work by epic, not by project | Accepted |
| [0018](0018-gate-journey-stages-on-recorded-run-status.md) | Gate the journey's stages on the status each stage records while it runs | Accepted, amended by 0027 and 0028 |
| [0019](0019-remove-role-subscriptions.md) | Remove role subscriptions, and drive board discovery from named companies | Accepted, amended by 0030 |
| [0020](0020-analyse-ten-roles-and-build-the-map-after-every-analysis.md) | Analyse ten roles, fixed by the system, and build the role map after every analysis | Accepted, amended by 0024, 0027 and 0029 |
| [0021](0021-let-users-add-custom-roles-beside-the-ten.md) | Let users add roles of their own beside the ten, and make a pasted JD belong to one | Superseded by 0030 |
| [0022](0022-make-a-target-a-role-and-an-optional-opening.md) | Make a Target a role, plus an optional opening in it | Accepted, amended by 0030 and 0032 |
| [0023](0023-ask-questions-per-gap-of-the-target-in-fill-the-gap.md) | Ask questions per gap of the Target, in Fill the gap, and submit the answers together | Accepted |
| [0024](0024-recommend-roles-from-the-assessment-and-keep-the-ten-the-market-has.md) | Recommend roles from the strength assessment, keep the ten the market has, and score fits once per build | Accepted, amended by 0027, 0028, 0029 and 0031 |
| [0025](0025-search-himalayas-for-the-candidate-roles.md) | Search Himalayas for the analysis's candidate roles, as ownerless demand sources | Accepted, amended by 0026 and 0027 |
| [0026](0026-choose-target-locations-from-a-list-of-countries-regions-and-remote.md) | Choose target locations from a list of countries, regions and Remote | Accepted |
| [0027](0027-fetch-the-market-only-when-a-build-needs-it.md) | Fetch the market only when a build needs it, and build the role map only when asked | Accepted, amended by 0030 and 0031 |
| [0028](0028-score-the-fit-in-the-role-map.md) | Score the fit in the role map, against the scores the analysis hands over | Accepted, amended by 0032 |
| [0029](0029-set-the-candidate-count-and-the-top-k-as-settings.md) | Set the candidate count and the top k as settings, and spend only on the k | Accepted |
| [0030](0030-aim-at-a-posting-of-your-own-instead-of-adding-a-custom-role.md) | Aim the Advisor at a posting of your own instead of adding a custom role | Accepted, amended by 0033 |
| [0031](0031-record-what-a-build-made-of-each-candidate-on-the-build.md) | Keep a role candidate as a query, and record what a build made of it on the build | Accepted |
| [0032](0032-work-out-every-openings-fit-locally-from-its-roles.md) | Work out every opening's fit locally from its role's, and rank a role's openings by it | Accepted |
| [0033](0033-keep-a-posting-of-your-own-in-target.md) | Keep a posting of your own in Target, and score it with the role map's fit kit | Accepted |
| [0034](0034-add-a-role-of-your-own-without-evaluating-it.md) | Add a role of your own without spending anything, and evaluate it when it is set as the target | Accepted |
| [0035](0035-regenerate-the-plan-and-resume-only-when-asked.md) | Regenerate the gap plan and résumé only when the user asks, and say when they are outdated | Accepted |
| [0036](0036-let-a-gap-plan-cite-the-answers-given-about-each-gap.md) | Let a gap plan cite the answers given about each gap, including an uncovered requirement | Accepted |
| [0037](0037-read-each-fact-with-its-date.md) | Read each fact with its date, and let a newer fact win over an older one it contradicts | Accepted |
| [0038](0038-export-the-resume-as-previewed-and-download-it.md) | Make the PDF renderer the source of a résumé's look, and download the export directly | Accepted |
| [0039](0039-let-the-user-choose-a-resumes-sections.md) | A résumé is an ordered list of sections the user chooses | Accepted |
| [0040](0040-keep-resume-templates-as-checked-specs.md) | A résumé template is a checked spec, and a user can keep their own | Accepted |
| [0041](0041-start-a-template-from-a-pdf-read-for-its-style-only.md) | A template can start from a PDF, read locally for its style only | Accepted |
| [0042](0042-run-advisor-jobs-in-the-background-with-stages-and-cancel.md) | Advisor jobs run in the background, record their stage, and can be cancelled | Accepted |
| [0043](0043-write-every-resume-section-at-once-and-show-what-the-user-picks.md) | A résumé writes every section at once, and the user picks which to show | Accepted |
| [0044](0044-let-a-resume-claim-a-gap-from-the-answers-given-about-it.md) | A résumé may claim a gap from the answers given about it, and nothing else | Accepted |
| [0045](0045-read-the-career-timeline-in-the-analysis.md) | The career timeline is the analysis's reading of the evidence | Accepted |
| [0046](0046-drop-an-unbacked-gap-claim-instead-of-rejecting-the-resume.md) | An unbacked gap claim is dropped, not the résumé | Accepted |
| [0047](0047-let-a-resume-set-its-own-fonts-over-its-template.md) | A résumé may set its own fonts over its template's | Accepted |
| [0048](0048-draw-contact-details-as-typed-items-with-icons.md) | Contact details are typed items, drawn with icons | Accepted |
| [0049](0049-list-a-roles-openings-newest-first-without-a-fit.md) | The role map lists a role's openings newest first, without a fit | Accepted |

Decisions taken before this directory existed are recorded in the tables of
`docs/domain_model.md` section 6 and `docs/architecture.md`
sections 7 and 8.

Records accepted before 2026-09-27 cite `docs/technical_boundaries.md`. That is
now `docs/architecture.md`, with the same section numbers.

Records accepted before 2026-09-29 cite `prototype/Career Advisor.dc.html` and
`prototype/_ds/organic-*`. The prototype is now one screen per file under
`prototype/screens/`, described in `prototype/README.md`, and the Organic
stylesheet it was built on lives on as `web/src/styles/organic.css`.
