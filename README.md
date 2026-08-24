# hu-eli-mcp

<!-- mcp-name: io.github.matematicsolutions/hu-eli-mcp -->

An MCP server for **Hungary's official national legislation database**, the Nemzeti
Jogszabalytar (NJT, `njt.jog.gov.hu`), maintained by MKIFK. It gives an AI agent a piece of
Hungarian legislation resolved by its **native ELI** (European Legislation Identifier), with a
verifiable citation: the ELI itself, a human-readable citation, and a link to the official
source.

Part of the **eu-legal-mcp** line by [MateMatic](https://matematic.co) — one connector per EU
member state, the same citation contract everywhere.

> **On ELI.** Unlike the Netherlands and Sweden (earlier connectors in this line, neither of
> which publishes native ELI), **Hungary has a genuine, documented national ELI
> implementation since 2023** (`njt.jog.gov.hu/eli/urisemak`). `eli_uri` is therefore the real
> `/eli/` URI the tool resolved — never a substitute identifier. See `DISCOVERY.md`.

## Tools

| Tool | What it does |
|---|---|
| `hu_get_act(year, serial)` | Metadata for a Hungarian Act (torveny) by ELI, e.g. year `2013`, serial `5` (the Civil Code). No issuer code needed. |
| `hu_get_legislation(doc_type, year, issuer, serial)` | Metadata for any other legislation (decrees etc.) by ELI — type, year, issuer (case-sensitive) and serial. |
| `hu_get_text(doc_type, year, serial, issuer=None)` | The full document HTML content for either an Act or other legislation. |
| `hu_list_doc_types()` | Valid NJT document-type codes (e.g. `TV`=Act, `R`=decree). |
| `hu_list_issuers()` | Valid NJT issuer codes (e.g. `Korm`=Government) — note the exact casing matters. |
| `hu_coverage()` | Declare what this connector covers, when each family was captured, and - explicitly - what it does NOT cover. Every gap carries a fallback. |

Every response carries the **citation contract**:

- `eli_uri` — the native ELI URI resolved, e.g. `https://njt.jog.gov.hu/eli/TV/2013/5`.
- `human_readable_citation` — built from the parsed title + subtitle, e.g.
  *"2013. évi V. törvény (a Polgári Törvénykönyvről)"*.
- `source_url` — the browsable `njt.jog.gov.hu/jogszabaly/...` document page.

### No free-text search

NJT has no REST/JSON API and its search/browse UI is a JavaScript SPA requiring a session
(not usable headlessly). Documents must be addressed by a **known ELI** — use
`hu_list_doc_types` / `hu_list_issuers` to discover valid codes, then `hu_get_act` /
`hu_get_legislation`. An unresolvable ELI (wrong year/serial/issuer, or wrong issuer-code
case) surfaces as `not_found` — NJT itself redirects it to a search-assist page rather than
a 404.

## Install

```bash
pip install -e ".[dev]"
```

Register it with your MCP client (see `.mcp.json.example`):

```json
{
  "mcpServers": {
    "hu-eli-mcp": {
      "command": "hu-eli-mcp",
      "env": {
        "HU_ELI_BASE_URL": "https://njt.jog.gov.hu",
        "HU_ELI_CACHE_DIR": "~/.matematic/cache/hu-eli",
        "HU_ELI_AUDIT_DIR": "~/.matematic/audit"
      }
    }
  }
}
```

### Windows 11 with Smart App Control

Smart App Control blocks unsigned executables, which covers `uvx.exe`, `pip.exe`
and the `hu-eli-mcp.exe` launcher that pip writes at install time. The `python.exe` and
`py.exe` from the python.org installer are signed by the Python Software
Foundation, so running the module through the interpreter works:

```bash
python -m pip install hu-eli-mcp
python -m hu_eli_mcp
```

`pip.exe` is blocked for the same reason, so install with `python -m pip`, not
`pip install`. If `python` is not on PATH, use the Windows launcher: `py -3 -m hu_eli_mcp`.

```json
{ "mcpServers": { "hu-eli-mcp": { "command": "python", "args": ["-m", "hu_eli_mcp"] } } }
```

Do not turn Smart App Control off to work around this - it cannot be re-enabled
without reinstalling Windows.

## Design

- **Public data only.** Read-only against the keyless, official `njt.jog.gov.hu`; nothing is
  sent beyond the ELI path being resolved. Honors `robots.txt` (never calls `/search/*`).
- **Audit log.** Every call appends one JSON line to `~/.matematic/audit/hu-eli-mcp.jsonl`
  (AI Act art. 12 record-keeping).
- **Vendor-neutral.** No LLM provider, no telemetry; own backoff + on-disk cache.
- **No fabrication.** The ELI, title and citation are parsed from the resolved document page.
  If NJT's markup changes, the connector fails loudly rather than returning stale or invented
  data.

See `CONSTITUTION.md` (the 4 principles) and `DISCOVERY.md` (how the source was mapped,
including the `njt.hu` → `njt.jog.gov.hu` domain discovery and the issuer-code casing gotcha).

## Tests

```bash
pytest tests/test_instructions_drift.py   # offline
pytest tests/test_smoke.py                 # live NJT
```

## Licence

Apache-2.0. The Hungarian legislation served is official public data of Hungary; this
connector adds no rights over it.
