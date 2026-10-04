"""Résumé export: content to HTML to PDF (ADR 0007, ADR 0038, ADR 0040).

Export is presentation, not a domain rule (section 2.9). How a résumé looks is
its template's ``TemplateSpec``, which the SPA's preview reads too, so the PDF
is the page the user previewed. The CSS is built only from the spec's checked
values — enums, numbers in their ranges, ``#rrggbb`` colours and fonts from a
fixed list — so nothing a user writes reaches it. Type is set in fonts
installed in the image, found by fontconfig, with DejaVu for anything outside
them. Every value of the content is escaped and nothing external is
referenced, so a résumé's text can never make the renderer reach the network.
The grey source notes stay in the app; a résumé sent to a company does not
carry them.
"""

from __future__ import annotations

from html import escape

from advisor.resume.domain import (
    TRIMMED_BULLETS,
    TRIMMED_SKILLS,
    Bullet,
    BulletStyle,
    HeadingCase,
    Layout,
    Options,
    ResumeContent,
    Section,
    SectionShape,
    TemplateSpec,
)
from advisor.resume.domain.constants import (
    FALLBACK_FONT,
    PAGE_MARGIN_SIDE_MM,
    PAGE_MARGIN_TOP_MM,
)

# The en dash as a CSS escape; the two spaces leave one after it.
_MARKERS = {BulletStyle.DOT: "disc", BulletStyle.DASH: '"\\2013  "', BulletStyle.NONE: "none"}


def render_html(content: ResumeContent, *, spec: TemplateSpec, options: Options) -> str:
    heading = f'"{spec.heading_font}", "{FALLBACK_FONT}", serif'
    body = f'"{spec.body_font}", "{FALLBACK_FONT}", sans-serif'
    title_pt, contact_pt, small_pt = spec.get_derived_pt()
    contact = escape(" · ".join(p for p in (content.headline, content.contact) if p))
    # A hidden section is kept in the résumé and never printed (ADR 0043).
    content = content.get_shown()
    main = [s for s in content.sections if not spec.is_in_sidebar(s.kind)]
    side = [s for s in content.sections if spec.is_in_sidebar(s.kind)]
    main_html = "".join(_section(s, trim=options.trim) for s in main)
    if spec.layout.has_sidebar:
        side_html = f'<div class="contact">{contact}</div>' + "".join(
            _section(s, trim=options.trim) for s in side
        )
        columns = (
            (side_html, main_html) if spec.layout is Layout.SIDEBAR_LEFT else (main_html, side_html)
        )
        classes = ("side", "main") if spec.layout is Layout.SIDEBAR_LEFT else ("main", "side")
        body_html = (
            f"<header><h1>{escape(content.name)}</h1></header>"
            '<div class="columns">'
            + "".join(
                f'<div class="{cls}">{html}</div>'
                for cls, html in zip(classes, columns, strict=True)
            )
            + "</div>"
        )
    else:
        band = ' class="band"' if spec.layout is Layout.HEADER_BAND else ""
        body_html = (
            f"<header{band}><h1>{escape(content.name)}</h1>"
            f'<div class="contact">{contact}</div></header>{main_html}'
        )
    marker = _MARKERS[spec.bullet]
    transform = "uppercase" if spec.heading_case is HeadingCase.UPPER else "none"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(content.name)}</title>
<style>
@page {{ size: A4; margin: {PAGE_MARGIN_TOP_MM}mm {PAGE_MARGIN_SIDE_MM}mm; }}
body {{ font-family: {body}; font-size: {spec.body_pt}pt; color: {spec.text_color};
       background: #ffffff; line-height: 1.5; margin: 0; }}
header {{ border-bottom: {spec.get_rule_css()}; padding-bottom: 10pt; margin-bottom: 14pt; }}
header.band {{ background: {spec.get_band_color()}; padding: 10pt 12pt; }}
h1 {{ font-family: {heading}; font-size: {spec.name_pt}pt; line-height: 1.1;
     color: {spec.name_color}; margin: 0; font-weight: 400; }}
.contact {{ font-size: {contact_pt}pt; color: #5a5550; margin-top: 4pt; }}
h2 {{ font-size: {spec.heading_pt}pt; letter-spacing: 0.1em; text-transform: {transform};
     font-weight: 800; color: {spec.name_color}; margin: 14pt 0 6pt; }}
.columns {{ display: flex; gap: 14pt; }}
.side {{ width: 30%; flex: 0 0 auto; }}
.main {{ flex: 1; min-width: 0; }}
.summary {{ margin: 0; }}
.job {{ margin-bottom: 10pt; page-break-inside: avoid; }}
.job-head {{ display: flex; justify-content: space-between; gap: 12pt; }}
.job-title {{ font-family: {heading}; font-size: {title_pt}pt; }}
.job-when {{ font-size: {small_pt}pt; color: #6b6560; white-space: nowrap; }}
.job-link {{ font-size: {small_pt}pt; color: #6b6560; }}
ul {{ margin: 4pt 0 0; padding-left: 12pt; list-style: {marker}; }}
li {{ margin-bottom: 3pt; }}
li::marker {{ color: {spec.accent_color}; }}
.skills {{ display: flex; flex-wrap: wrap; gap: 5pt; }}
.skill {{ font-size: {small_pt}pt; padding: 2pt 8pt; border-radius: 999px;
         background: #f3f1ee; color: #3d3a36; }}
</style></head>
<body>
{body_html}
</body></html>"""


def _section(section: Section, *, trim: bool) -> str:
    """One section, by its shape. An empty one prints nothing at all."""
    if section.is_empty:
        return ""
    title = f"<h2>{escape(section.heading)}</h2>"
    if section.shape is SectionShape.TEXT:
        return f'{title}<p class="summary">{escape(section.text)}</p>'
    if section.shape is SectionShape.LIST:
        items = section.items[:TRIMMED_SKILLS] if trim else section.items
        chips = "".join(f'<span class="skill">{escape(i)}</span>' for i in items)
        return f'{title}<div class="skills">{chips}</div>'
    if section.shape is SectionShape.BULLETS:
        return f"{title}{_lines(section.bullets, trim=trim)}"
    entries = []
    for entry in section.entries:
        name = " — ".join(escape(part) for part in (entry.title, entry.org) if part)
        link = f'<div class="job-link">{escape(entry.link)}</div>' if entry.link else ""
        entries.append(
            '<section class="job">'
            '<div class="job-head">'
            f'<span class="job-title">{name}</span>'
            f'<span class="job-when">{escape(entry.when)}</span>'
            "</div>"
            f"{link}{_lines(entry.bullets, trim=trim)}"
            "</section>"
        )
    return title + "".join(entries)


def _lines(bullets: tuple[Bullet, ...], *, trim: bool) -> str:
    shown = bullets[:TRIMMED_BULLETS] if trim else bullets
    if not shown:
        return ""
    return "<ul>" + "".join(f"<li>{escape(b.text)}</li>" for b in shown) + "</ul>"


def render_pdf(html: str) -> bytes:
    """Worker ``docs`` queue only: rendering is CPU and memory, never a request."""
    # Imported here so the api, which never renders, does not load Pango.
    from weasyprint import HTML
    from weasyprint.urls import FatalURLFetchingError, URLFetcher

    class NoFetching(URLFetcher):  # type: ignore[misc]
        """Nothing in a résumé should be fetched; anything that tries stops it."""

        def fetch(self, url: str, headers: object = None) -> object:
            raise FatalURLFetchingError(f"export does not fetch external resources: {url[:80]}")

    try:
        document = HTML(string=html, url_fetcher=NoFetching(fail_on_errors=True))
        return bytes(document.write_pdf())
    except FatalURLFetchingError as exc:
        raise ValueError(str(exc)) from exc
