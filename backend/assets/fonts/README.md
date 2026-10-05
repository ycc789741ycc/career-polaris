# Résumé fonts

The fonts the résumé PDF is set in (ADR 0038), installed in the image under
`/usr/local/share/fonts/careerpolaris/` where fontconfig finds them. Pango loads them by
family name, so the renderer never fetches a font.

They are the SPA's self-hosted files (`web/src/styles/fonts/*.woff2`, Latin
subset), converted to TTF so the preview and the PDF set the same type:

| File | Family | Weight |
|---|---|---|
| `caprasimo-latin-400-normal.ttf` | Caprasimo | 400 |
| `figtree-latin-400-normal.ttf` | Figtree | 400 |
| `figtree-latin-800-normal.ttf` | Figtree | 800, ExtraBold |
| `inter-latin-{400,700}-normal.ttf` | Inter | 400, 700 |
| `lato-latin-{400,700}-normal.ttf` | Lato | 400, 700 |
| `source-serif-4-latin-{400,700}-normal.ttf` | Source Serif 4 | 400, 700 |
| `merriweather-latin-{400,700}-normal.ttf` | Merriweather | 400, 700 |
| `eb-garamond-latin-{400,700}-normal.ttf` | EB Garamond | 400, 700 |
| `ibm-plex-mono-latin-{400,700}-normal.ttf` | IBM Plex Mono | 400, 700 |

The conversion also rewrites each file's name table and weight class: the
web subsets name Figtree "Figtree Light", which fontconfig would not match to
"Figtree". The six families from Inter on are Fontsource's Latin TTFs as
published, except Merriweather, whose name table says "Merriweather Light
18pt" and is rewritten to "Merriweather". Every family here is SIL Open Font
License 1.1; the licences sit beside the files.

A template may also name DejaVu Serif or DejaVu Sans Mono (ADR 0040). Those
come from the image's `fonts-dejavu-core` package, not from here; the SPA
hosts Latin subsets of the same files (`web/src/styles/fonts/dejavu-*`).
