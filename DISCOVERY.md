# DISCOVERY - Hungary (Nemzeti Jogszabalytar / NJT via njt.jog.gov.hu)

Date: 2026-07-06. Status: **BUILD** (grounding MVP shipped).

## Source

Hungary's national legislation is published in the **Nemzeti Jogszabalytar** (NJT, "National
Legislation Database"), maintained by MKIFK (Magyar Kozlonykiado es Igazsagugyi
Forditokozpont Zrt.). The historical domain `njt.hu` is now fronted by bot-protection
(BigIP WAF) that resets every non-browser HTTPS connection (verified: `curl`, PowerShell
`Invoke-WebRequest`, and Anthropic's own `WebFetch` infrastructure all got `ECONNRESET`/
`Recv failure` on `njt.hu`, while plain HTTP got a clean 302 to the same host). The **current,
live application domain is `njt.jog.gov.hu`**, discovered via web search (Hungarian ELI schema
docs and case-law citations all point there). `njt.jog.gov.hu` is directly reachable
(`Server: Apache`, `X-Powered-By: PHP/7.3.33`, HTTP 200/302/404 as expected, no WAF reset).

## Shape: no REST/JSON API, native ELI + server-rendered HTML documents

`njt.jog.gov.hu` is an AngularJS SPA (`data-ng-app="njtAppX"`). Its internal AJAX endpoints
(`/ajax/*.json`) require a session cookie (`__Secure-sessid`) and are not a documented public
API - they are private frontend plumbing, not used by this connector. **Search and browse
pages are client-rendered** (confirmed: `/search/torveny/1/10` and `/eli/TV/2015` both return
200 with an empty AngularJS shell and zero server-rendered result links).

However, **the individual document page IS server-rendered HTML**, reachable with no
JavaScript and no cookies:

- `GET /jogszabaly/{doc_id}` (e.g. `/jogszabaly/2013-5-00-00`) returns HTTP 200 with the full
  consolidated legal text inline (verified: 1900+ section markers for the Hungarian Civil
  Code, 2013. evi V. torveny). A nonexistent `doc_id` returns a clean HTTP 404.
- **Hungary has a genuine, documented native ELI implementation since 2023**
  (`https://njt.jog.gov.hu/eli/urisemak`, "Hazai ELI URI semak" — the national ELI URI schema
  page). ELI URIs resolve with an HTTP 302 redirect to the `/jogszabaly/{doc_id}` page:
  - `GET /eli/TV/2013/5` → `302 Location: /jogszabaly/2013-5-00-00` (verified: Hungarian
    Civil Code).
  - `GET /eli/R/2016/Korm/428` → `302 Location: /jogszabaly/2016-428-20-22` (verified: a real
    Government decree, 428/2016 (XII.15.) Korm. rendelet, found via web search).
  - An **unresolvable** ELI (wrong year/serial/issuer, or wrong issuer-code casing) redirects
    instead to `/eli/kereses`, NJT's own search-assist page — this is the documented behaviour
    ("Amikor a rendszer egy hibas hivatkozasi format kap...", per `/eli/urisemak`), not an
    error page, so this connector treats a redirect to `/eli/kereses` as `not_found`.
- `robots.txt` explicitly `Allow`s `/jogszabaly/*` and does not disallow `/eli/*`; only
  `/search/*` is disallowed (never called by this connector).

## ELI URI forms (from `/eli/urisemak`)

- **Acts (torveny)**: `https://njt.jog.gov.hu/eli/TV/{ev}[/{sr}/{date}/{nyelv}/{ffmt}]` — no
  issuer code needed. Example: `/eli/TV/2013/5`.
- **General form (everything else - decrees etc.)**:
  `https://njt.jog.gov.hu/eli/{tip}/{ev}/{kib}[/{sr}/{date}/{nyelv}/{ffmt}]` — type + year +
  issuer are mandatory. **The issuer code is case-sensitive**: the Government's code is
  `Korm` (mixed case; `KORM` fails and redirects to the search-assist page). Valid codes are
  listed at `/eli/kibocsatokodok` (a plain two-column HTML table, ~165 rows) and valid
  document types at `/eli/tipuskodok` (~19 rows), both server-rendered.
- Optional trailing parameters (`date`, `kozlony`, language, format) exist per the schema docs
  but are out of scope for this MVP (see CONSTITUTION.md Open Points).

## Document page landmarks (parsed by `citations.py`)

```html
<h1 class="pslice jogszabalyMainTitle mainTitle">2013. évi V. törvény</h1>
<h2 class="pslice jogszabalySubtitle">a Polgári Törvénykönyvről<sup ...>1</sup></h2>
<div class="hataly">2026.03.01.</div>
```

- `h1.jogszabalyMainTitle` → the citation number (`title`).
- `h2.jogszabalySubtitle` → the subject of the act (`subtitle`); footnote `<sup>` markers are
  stripped.
- `div.hataly` → the "hatalyos" (in force) as-of date NJT displays for the resolved version, if
  present (`in_force_date`).

## Citation contract (Art. IV)

| Field | Source | Example |
|---|---|---|
| `eli_uri` | the native ELI path the caller requested/resolved | `https://njt.jog.gov.hu/eli/TV/2013/5` |
| `human_readable_citation` | `title` + `subtitle`, parsed from the document page | `2013. évi V. törvény (a Polgári Törvénykönyvről)` |
| `source_url` | the resolved `/jogszabaly/{doc_id}` page | `https://njt.jog.gov.hu/jogszabaly/2013-5-00-00` |

**ELI note (decisive, and the opposite of NL/SE).** Unlike the Netherlands and Sweden — earlier
connectors in this line, neither of which publishes native ELI — **Hungary genuinely has a
documented, native ELI implementation**. `eli_uri` is therefore the real `/eli/` URI, not a
substitute identifier.

## Tools

- `hu_get_act(year, serial)` — resolves `/eli/TV/{year}/{serial}`, the citation contract.
- `hu_get_legislation(doc_type, year, issuer, serial)` — resolves
  `/eli/{doc_type}/{year}/{issuer}/{serial}` for anything other than Acts.
- `hu_get_text(doc_type, year, serial, issuer=None)` — same resolution, returns the full
  document HTML content.
- `hu_list_doc_types()` — parses `/eli/tipuskodok`.
- `hu_list_issuers()` — parses `/eli/kibocsatokodok` (note the case-sensitivity of codes).

## Open points

- No free-text or title search is possible headlessly (see CONSTITUTION.md Open Points #1).
- Historical/gazette (`kozlony`) date-pinned versions are part of the documented ELI schema
  but not yet exposed as explicit tool parameters (CONSTITUTION.md Open Points #3).
- Municipal decrees (`onkormanyzati rendeletek`) have a separate ELI form
  (`/eli/{ortip}/{ev}/{orkib}/{sr}`) noted in the schema docs but not covered by this MVP.
