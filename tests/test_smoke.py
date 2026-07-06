"""Live smoke tests against the real Nemzeti Jogszabalytar (njt.jog.gov.hu).

These hit the network. They are skipped automatically if the host is unreachable. Run
explicitly with:

    pytest tests/test_smoke.py
"""

from __future__ import annotations

import httpx
import pytest

from hu_eli_mcp.server import (
    ToolError,
    hu_get_act,
    hu_get_legislation,
    hu_get_text,
    hu_list_doc_types,
    hu_list_issuers,
)

CIVIL_CODE_YEAR = "2013"
CIVIL_CODE_SERIAL = "5"
KNOWN_DECREE_YEAR = "2016"
KNOWN_DECREE_ISSUER = "Korm"
KNOWN_DECREE_SERIAL = "428"


def _live_or_skip() -> None:
    try:
        r = httpx.get("https://njt.jog.gov.hu/eli/urisemak", timeout=20.0)
        r.raise_for_status()
    except Exception as exc:  # pragma: no cover - network gate
        pytest.skip(f"njt.jog.gov.hu not reachable: {exc}")


@pytest.mark.asyncio
async def test_smoke_get_act_civil_code():
    _live_or_skip()
    act = await hu_get_act(CIVIL_CODE_YEAR, CIVIL_CODE_SERIAL)
    assert act.year == CIVIL_CODE_YEAR
    assert act.serial == CIVIL_CODE_SERIAL
    assert act.eli_uri == "https://njt.jog.gov.hu/eli/TV/2013/5"
    assert act.title and "2013" in act.title
    assert act.subtitle and "Polg" in act.subtitle
    assert act.human_readable_citation
    assert act.source_url and act.source_url.startswith("https://njt.jog.gov.hu/jogszabaly/")


@pytest.mark.asyncio
async def test_smoke_get_legislation_decree():
    _live_or_skip()
    decree = await hu_get_legislation(
        "R", KNOWN_DECREE_YEAR, KNOWN_DECREE_ISSUER, KNOWN_DECREE_SERIAL
    )
    assert decree.doc_type == "R"
    assert decree.issuer == "Korm"
    assert decree.eli_uri == "https://njt.jog.gov.hu/eli/R/2016/Korm/428"
    assert decree.title and "428" in decree.title
    assert decree.human_readable_citation
    assert decree.source_url


@pytest.mark.asyncio
async def test_smoke_get_text():
    _live_or_skip()
    text = await hu_get_text("TV", CIVIL_CODE_YEAR, CIVIL_CODE_SERIAL)
    assert text.content and text.byte_size and text.byte_size > 100_000
    assert "jogszabalyMainTitle" in text.content
    assert text.eli_uri and text.human_readable_citation and text.source_url


@pytest.mark.asyncio
async def test_smoke_not_found_bad_serial():
    _live_or_skip()
    with pytest.raises(ToolError) as exc_info:
        await hu_get_act(CIVIL_CODE_YEAR, "999999")
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_smoke_not_found_wrong_issuer_case():
    _live_or_skip()
    with pytest.raises(ToolError) as exc_info:
        await hu_get_legislation("R", KNOWN_DECREE_YEAR, "KORM", KNOWN_DECREE_SERIAL)
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_smoke_list_doc_types():
    _live_or_skip()
    result = await hu_list_doc_types()
    assert result.items
    codes = {item.code for item in result.items}
    assert "TV" in codes or "Alaptv" in codes


@pytest.mark.asyncio
async def test_smoke_list_issuers():
    _live_or_skip()
    result = await hu_list_issuers()
    assert result.items
    codes = {item.code for item in result.items}
    assert "Korm" in codes
