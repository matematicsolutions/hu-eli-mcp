"""FastMCP entry point - Hungarian national legislation (Nemzeti Jogszabalytar) tools.

Run:

    python -m hu_eli_mcp.server

Configuration via env:

- ``HU_ELI_CACHE_DIR`` (default ``~/.matematic/cache/hu-eli``)
- ``HU_ELI_AUDIT_DIR`` (default ``~/.matematic/audit``)
- ``HU_ELI_BASE_URL`` (default ``https://njt.jog.gov.hu``)
"""

from __future__ import annotations

import os
import re

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .audit import AuditLogger, hash_input, timer
from .citations import human_readable_citation, parse_code_table, parse_document_page
from . import runtime
from .client import DEFAULT_BASE_URL, HuError, HuNotFoundError, NjtClient
from .models import DocTypeInfo, DocTypeList, IssuerInfo, IssuerList, Legislation, LegislationText
from .coverage import Coverage, build_coverage

INSTRUCTIONS = """\
This MCP server exposes Hungary's official national legislation database, the Nemzeti Jogszabalytar (NJT, njt.jog.gov.hu), maintained by MKIFK. It has NO REST/JSON API - the search/browse UI is a JavaScript SPA that requires a session and is not usable headlessly. Instead, this server resolves Hungary's genuine, documented national ELI (European Legislation Identifier) URI scheme (published since 2023, see njt.jog.gov.hu/eli/urisemak) and fetches the resulting server-rendered document page. Every response carries a stable `eli_uri` (a real, native ELI - never fabricated), a `human_readable_citation` and a `source_url` (the citation contract).

## No free-text search

There is no headless full-text or title search. Documents must be addressed by a **known ELI**: a document type code, a year, a serial number, and (for everything except Acts) an issuer code. Use `hu_list_doc_types` and `hu_list_issuers` to discover valid codes; use `hu_get_act` for Acts (torveny) which need no issuer code, or `hu_get_legislation` for any other document type (government/ministerial decrees, etc.) which do.

## ELI shape

- Acts (torveny): `hu_get_act(year, serial)` -> ELI `/eli/TV/{year}/{serial}`.
- Everything else: `hu_get_legislation(doc_type, year, issuer, serial)` -> ELI `/eli/{doc_type}/{year}/{issuer}/{serial}`. **The issuer code is case-sensitive** (e.g. `Korm` for Government decrees, not `KORM` - use `hu_list_issuers` to get the exact casing).
- `hu_get_text` fetches the same document but returns the full HTML content (large; may be 100 KB-2 MB), not just metadata.

## Call order

1. `hu_list_doc_types` / `hu_list_issuers` - discover valid type/issuer codes if unknown.
2. `hu_get_act(year, serial)` or `hu_get_legislation(doc_type, year, issuer, serial)` - metadata: `eli_uri`, `title`, `subtitle`, `in_force_date`, `human_readable_citation`, `source_url`.
3. `hu_get_text(...)` - the full document HTML content, same identifying parameters.

## Hard constraints

- **Do not answer past the edge of this corpus** - when a search comes back empty, or the question touches material this connector does not carry, call `hu_coverage` and relay what it says is missing. Absence here is not absence in the law.
- **eli_uri is a genuine native ELI** - Hungary has published a documented ELI implementation since 2023; this server never constructs a substitute identifier.
- **No free-text search** - only get-by-known-identifier. An unresolvable identifier (wrong year/serial/issuer/casing) makes NJT redirect to its own search-assist page; this server surfaces that as `not_found` rather than guessing.
- **Consolidated ("hatalyos") text by default** - the resolved document is the version currently in force; `in_force_date` (if present on the page) states the as-of date NJT itself displays.
- **Every response has `human_readable_citation` + `source_url`** - cite both to the user.
- **No modification of official text** - returned verbatim from njt.jog.gov.hu.
- **Audit log JSONL** - every tool call appends to `~/.matematic/audit/hu-eli-mcp.jsonl`.

## Error iteration

Tools return a structured error with a `[code]` prefix:
- `invalid_arg` - a parameter is missing or malformed (e.g. a non-numeric year/serial).
- `not_found` - NJT could not resolve the ELI (redirected to its search-assist page) or the document page 404s.
- `upstream_error` - an NJT HTTP error (timeout, 5xx, transport failure). Retry once before surfacing.

## Response style

- Cite legislation as `human_readable_citation` with the `source_url`: "2013. evi V. torveny (a Polgari Torvenykonyvrol), https://njt.jog.gov.hu/jogszabaly/2013-5-00-00".
- NEVER invent a doc_type code, an issuer code, a title or an ELI - take each from the tool output or from `hu_list_doc_types` / `hu_list_issuers`.
"""

_YEAR_RE = re.compile(r"^\d{4}$")
_SERIAL_RE = re.compile(r"^[A-Za-z0-9./-]+$")
_CODE_RE = re.compile(r"^[A-Za-z_]+$")


class ToolError(Exception):
    """Structured error for hu-eli MCP tools - visible to the LLM with a [code] prefix."""

    VALID_CODES = frozenset({"invalid_arg", "not_found", "upstream_error"})

    def __init__(self, code: str, message: str):
        if code not in self.VALID_CODES:
            raise ValueError(f"Unknown ToolError code: {code}. Valid: {sorted(self.VALID_CODES)}")
        self.code = code
        super().__init__(f"[{code}] {message}")


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=True,
)

mcp: FastMCP = FastMCP(name="hu-eli-mcp", instructions=INSTRUCTIONS)


def _base_url() -> str:
    return os.environ.get("HU_ELI_BASE_URL", runtime.base_url("eli", DEFAULT_BASE_URL)).rstrip("/")


def _audit() -> AuditLogger:
    return AuditLogger()


def _map_upstream(exc: Exception) -> Exception:
    if isinstance(exc, HuNotFoundError):
        return ToolError("not_found", str(exc))
    if isinstance(exc, HuError):
        return ToolError("upstream_error", str(exc))
    import httpx

    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return ToolError("not_found", "NJT returned 404 for this document.")
    if isinstance(exc, (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException)):
        return ToolError("upstream_error", f"NJT error: {type(exc).__name__}: {exc}")
    return exc


def _check_year(year: str) -> str:
    cleaned = str(year).strip()
    if not _YEAR_RE.match(cleaned):
        raise ToolError("invalid_arg", f"year={year!r} must be a 4-digit year, e.g. '2013'.")
    return cleaned


def _check_serial(serial: str) -> str:
    cleaned = str(serial).strip()
    if not cleaned or not _SERIAL_RE.match(cleaned):
        raise ToolError("invalid_arg", f"serial={serial!r} must be a non-empty NJT serial number.")
    return cleaned


def _check_code(label: str, code: str) -> str:
    cleaned = str(code).strip()
    if not cleaned or not _CODE_RE.match(cleaned):
        raise ToolError("invalid_arg", f"{label}={code!r} must be a non-empty NJT code (letters only).")
    return cleaned


def _to_legislation(
    *, doc_type: str, year: str, serial: str, issuer: str | None, eli_path: str,
    source_url: str, parsed: dict[str, str],
) -> Legislation:
    return Legislation(
        doc_type=doc_type,
        year=year,
        serial=serial,
        issuer=issuer,
        title=parsed.get("title"),
        subtitle=parsed.get("subtitle"),
        in_force_date=parsed.get("in_force_date"),
        eli_uri=f"{_base_url()}{eli_path}",
        human_readable_citation=human_readable_citation(parsed.get("title"), parsed.get("subtitle")),
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# hu_get_act
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def hu_get_act(year: str, serial: str) -> Legislation:
    """Fetch metadata for a Hungarian Act (torveny) by its ELI (year + serial).

    Args:
        year: 4-digit year, e.g. ``"2013"``.
        serial: the Act's serial number within that year, e.g. ``"5"`` (2013. evi V. torveny
            is Act no. 5 of 2013, the Hungarian Civil Code).

    Returns:
        ``Legislation`` with ``eli_uri``, ``title``, ``subtitle``, ``human_readable_citation``,
        ``source_url``.
    """
    audit = _audit()
    y = _check_year(year)
    s = _check_serial(serial)
    eli_path = f"/eli/TV/{y}/{s}"
    input_hash = hash_input({"tool": "hu_get_act", "year": y, "serial": s})

    with timer() as t:
        try:
            async with NjtClient(base_url=_base_url()) as client:
                source_url, html = await client.resolve_eli(eli_path)
        except Exception as exc:
            audit.log(tool="hu_get_act", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    parsed = parse_document_page(html)
    result = _to_legislation(
        doc_type="TV", year=y, serial=s, issuer=None, eli_path=eli_path,
        source_url=source_url, parsed=parsed,
    )
    audit.log(tool="hu_get_act", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# hu_get_legislation
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def hu_get_legislation(doc_type: str, year: str, issuer: str, serial: str) -> Legislation:
    """Fetch metadata for any Hungarian legislation by its ELI (type + year + issuer + serial).

    Use this for anything other than Acts (torveny) - government decrees, ministerial decrees,
    etc. Use `hu_list_doc_types` for valid `doc_type` codes and `hu_list_issuers` for valid
    `issuer` codes (issuer codes are case-sensitive, e.g. `Korm` for Government).

    Args:
        doc_type: NJT type code, e.g. ``"R"`` (rendelet / decree).
        year: 4-digit year, e.g. ``"2016"``.
        issuer: NJT issuer code, case-sensitive, e.g. ``"Korm"`` (Government).
        serial: the document's serial number within that year, e.g. ``"428"``.

    Returns:
        ``Legislation`` with ``eli_uri``, ``title``, ``subtitle``, ``human_readable_citation``,
        ``source_url``.
    """
    audit = _audit()
    dt = _check_code("doc_type", doc_type)
    y = _check_year(year)
    iss = _check_code("issuer", issuer)
    s = _check_serial(serial)
    eli_path = f"/eli/{dt}/{y}/{iss}/{s}"
    input_hash = hash_input(
        {"tool": "hu_get_legislation", "doc_type": dt, "year": y, "issuer": iss, "serial": s}
    )

    with timer() as t:
        try:
            async with NjtClient(base_url=_base_url()) as client:
                source_url, html = await client.resolve_eli(eli_path)
        except Exception as exc:
            audit.log(tool="hu_get_legislation", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    parsed = parse_document_page(html)
    result = _to_legislation(
        doc_type=dt, year=y, serial=s, issuer=iss, eli_path=eli_path,
        source_url=source_url, parsed=parsed,
    )
    audit.log(tool="hu_get_legislation", input_hash=input_hash, output_count_or_size=1,
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# hu_get_text
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def hu_get_text(
    doc_type: str, year: str, serial: str, issuer: str | None = None
) -> LegislationText:
    """Fetch the full document HTML content of a Hungarian piece of legislation.

    For Acts (torveny), pass `doc_type="TV"` and omit `issuer`. For anything else, pass the
    `issuer` code (case-sensitive - use `hu_list_issuers`).

    Args:
        doc_type: NJT type code, e.g. ``"TV"`` (torveny / Act) or ``"R"`` (rendelet / decree).
        year: 4-digit year.
        serial: the document's serial number within that year.
        issuer: NJT issuer code, case-sensitive (required for everything except `"TV"`).

    Returns:
        ``LegislationText`` with the citation contract and ``content`` (the document's HTML).
    """
    audit = _audit()
    dt = _check_code("doc_type", doc_type)
    y = _check_year(year)
    s = _check_serial(serial)
    if dt == "TV":
        eli_path = f"/eli/TV/{y}/{s}"
        iss: str | None = None
    else:
        if not issuer:
            raise ToolError("invalid_arg", "issuer is required for doc_type other than 'TV'.")
        iss = _check_code("issuer", issuer)
        eli_path = f"/eli/{dt}/{y}/{iss}/{s}"
    input_hash = hash_input(
        {"tool": "hu_get_text", "doc_type": dt, "year": y, "issuer": iss, "serial": s}
    )

    with timer() as t:
        try:
            async with NjtClient(base_url=_base_url()) as client:
                source_url, html = await client.resolve_eli(eli_path)
        except Exception as exc:
            audit.log(tool="hu_get_text", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    parsed = parse_document_page(html)
    result = LegislationText(
        doc_type=dt,
        year=y,
        serial=s,
        issuer=iss,
        title=parsed.get("title"),
        subtitle=parsed.get("subtitle"),
        in_force_date=parsed.get("in_force_date"),
        eli_uri=f"{_base_url()}{eli_path}",
        human_readable_citation=human_readable_citation(parsed.get("title"), parsed.get("subtitle")),
        source_url=source_url,
        content=html,
        byte_size=len(html.encode("utf-8")),
    )
    audit.log(tool="hu_get_text", input_hash=input_hash, output_count_or_size=result.byte_size or 0,
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# hu_list_doc_types
# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def hu_list_doc_types() -> DocTypeList:
    """List valid NJT document-type codes (e.g. TV=Act, R=decree) from /eli/tipuskodok.

    Returns:
        ``DocTypeList`` with ``items: list[DocTypeInfo]`` (code + Hungarian name).
    """
    audit = _audit()
    input_hash = hash_input({"tool": "hu_list_doc_types"})

    with timer() as t:
        try:
            async with NjtClient(base_url=_base_url()) as client:
                html = await client.get_code_list("/eli/tipuskodok")
        except Exception as exc:
            audit.log(tool="hu_list_doc_types", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    rows = parse_code_table(html)
    items = [DocTypeInfo(code=code, name=name or None) for code, name in rows]
    result = DocTypeList(items=items)
    audit.log(tool="hu_list_doc_types", input_hash=input_hash, output_count_or_size=len(items),
              duration_ms=t.duration_ms, status="ok")
    return result


# ---------------------------------------------------------------------------
# hu_list_issuers
@mcp.tool(annotations=READ_ONLY)
async def hu_coverage() -> Coverage:
    """Declare what this connector covers, how it is sourced, and what it does NOT cover.

    Call this before telling a user that the law "does not contain" something, and whenever
    a search comes back empty: the absence may be a gap in this connector rather than in the
    law. Every gap carries a fallback saying where to look instead.

    Returns:
        ``Coverage`` with families, an as-of note, and a non-empty list of known gaps.
    """
    return build_coverage()


# ---------------------------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def hu_list_issuers() -> IssuerList:
    """List valid NJT issuer codes (case-sensitive, e.g. Korm=Government) from /eli/kibocsatokodok.

    Returns:
        ``IssuerList`` with ``items: list[IssuerInfo]`` (code + Hungarian name).
    """
    audit = _audit()
    input_hash = hash_input({"tool": "hu_list_issuers"})

    with timer() as t:
        try:
            async with NjtClient(base_url=_base_url()) as client:
                html = await client.get_code_list("/eli/kibocsatokodok")
        except Exception as exc:
            audit.log(tool="hu_list_issuers", input_hash=input_hash, output_count_or_size=0,
                      duration_ms=t.duration_ms if t.duration_ms else 0, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise _map_upstream(exc) from exc

    rows = parse_code_table(html)
    items = [IssuerInfo(code=code, name=name or None) for code, name in rows if code]
    result = IssuerList(items=items)
    audit.log(tool="hu_list_issuers", input_hash=input_hash, output_count_or_size=len(items),
              duration_ms=t.duration_ms, status="ok")
    return result


def main() -> None:
    """Run the MCP server over stdio (default for Claude Code)."""
    mcp.run()


if __name__ == "__main__":
    main()
