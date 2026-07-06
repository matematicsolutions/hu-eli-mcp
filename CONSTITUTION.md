# Constitution of hu-eli-mcp

Version: 0.1.0
Date: 2026-07-06
Licence: Apache-2.0

`hu-eli-mcp` is an MCP server for Hungary's official national legislation database, the
Nemzeti Jogszabalytar (NJT, `njt.jog.gov.hu`), maintained by MKIFK (Magyar Kozlonykiado es
Igazsagugyi Forditokozpont Zrt.). It resolves Hungary's native ELI (European Legislation
Identifier) URI scheme and fetches the resulting server-rendered document page, with a
verifiable citation.

The 4 principles below are inherited from the `eu-legal-mcp` line Constitution (Article IV).

---

## Art. 1. Public data only

NJT (`njt.jog.gov.hu`) is Hungary's official, free-to-use ("ingyenesen hasznalhato")
legislation database. The server is read-only and sends nothing beyond the ELI path it
resolves (document type, year, issuer, serial). There is no authentication and no REST/JSON
API; the server talks to the same public HTML endpoints a browser would reach, honoring
`robots.txt` (which explicitly `Allow`s `/jogszabaly/*` and does not block `/eli/*`; only
`/search/*` is disallowed, and this server never calls it).

## Art. 2. Mandatory audit log

Every tool call MUST append one JSON line to `~/.matematic/audit/hu-eli-mcp.jsonl`
(ts / tool / input_hash SHA-256 / output_count_or_size / duration_ms / status). Inability to
write = the tool returns an error, it does not silently skip.

## Art. 3. Vendor neutrality

No tool hardcodes an LLM provider, assumes a model, or adds commercial telemetry. The server
talks only to `njt.jog.gov.hu` and the local filesystem. Authentication: none; own backoff +
cache.

## Art. 4. A persistent identifier and a human-readable citation are mandatory

Every response MUST carry three fields:
- `eli_uri`: Hungary's **native** ELI URI (e.g. `https://njt.jog.gov.hu/eli/TV/2013/5`).
  Unlike the Netherlands and Sweden (earlier connectors in this line, which do not publish
  native ELI), **Hungary has a genuine, documented national ELI implementation since 2023**
  (`njt.jog.gov.hu/eli/urisemak`). This connector resolves the real ELI the caller supplied;
  it never constructs a substitute identifier.
- `human_readable_citation`: built from the parsed document title + subtitle, e.g.
  `"2013. evi V. torveny (a Polgari Torvenykonyvrol)"`.
- `source_url`: the resolved, browsable `njt.jog.gov.hu/jogszabaly/...` document page.

---

## Open points

1. **No free-text/title search.** NJT's search UI is a JavaScript SPA requiring a session; it
   is not usable headlessly. This connector only supports get-by-known-ELI (`hu_get_act`,
   `hu_get_legislation`). `hu_list_doc_types` / `hu_list_issuers` help a caller construct a
   valid ELI, but there is no way to discover a document by keyword alone.
2. **Issuer-code casing.** NJT's general ELI schema (`/eli/{tip}/{ev}/{kib}/{sr}`) requires the
   issuer code in its exact case (e.g. `Korm`, not `KORM`) — an incorrect case redirects to the
   search-assist page just like an unresolvable identifier. This is documented in
   `hu_list_issuers` and the tool INSTRUCTIONS rather than silently normalized, since NJT itself
   treats case as significant.
3. **Consolidated text only.** The connector always resolves the version NJT currently serves
   for the requested ELI (the "hatalyos" / in-force state unless the caller's own ELI already
   pins `kozlony` or a historical date via the appropriate URI form). A future version could
   expose the `date` / `kozlony` ELI parameters as explicit tool arguments.

## Evolution of the constitution

Changes to art. 1-4 follow SEMVER + an entry in `CHANGELOG.md` + a `pyproject.toml` bump.

First version: 2026-07-06. Author: Wieslaw Mazur / MateMatic.
