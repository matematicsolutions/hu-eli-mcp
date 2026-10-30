"""Offline regression tests for NJT's lazy-loaded legal text."""

from __future__ import annotations

import json

import httpx
import pytest

from hu_eli_mcp.cache import HttpCache
from hu_eli_mcp.client import HuError, NjtClient
from hu_eli_mcp.lazyload import find_deferred_groups, merge_deferred_groups

# Realistic NJT nested placeholder structure, including two adjacent ranges
# and a third range separated by already-rendered source text.
PAGE = """
<main>
<p>§338: available immediately</p>
<div id="sc-btk-1" class="pH borderStart" data-show-order="2943" data-b-n="1">
    <div id="sc-btk-11" class="pH" data-b-n="1"><span id="SZ339"></span></div>
</div><!--n-->
<div id="sc-btk-2" class="pH borderStart"
     data-show-order="3003" data-last-show-order="3062" data-b-n="2">
    <div id="sc-btk-22" class="pH" data-b-n="2"></div>
</div>
<p id="already-rendered">Keep this exact paragraph.</p>
<div id="sc-btk-3" class="pH borderStart" data-show-order="4443"
     data-last-show-order="4495" data-b-n="3">
    <div id="sc-btk-33" class="pH" data-b-n="3"></div>
</div>
<footer>Keep the footer.</footer>
</main>
"""

FRAGMENT_1 = (
    '<div id="sc-btk-1" class="bekezdesNyito">'
    '<span class="szakasz-jel">339.\u2005§</span> Garázdaság</div>'
    '<div id="sc-btk-2" class="bekezdesNyito">Other provisions</div>'
)
FRAGMENT_2 = (
    '<div id="sc-btk-3" class="bekezdesNyito">'
    '<span class="szakasz-jel">465.\u2005§</span> Final text</div>'
)


def test_find_groups_preserves_real_text_and_request_ranges():
    groups = find_deferred_groups(PAGE)
    assert len(groups) == 2
    assert len(groups[0].blocks) == 2
    assert groups[0].request_items() == [
        {"start": 2943}, {"start": 3003, "last": 3062}
    ]
    assert groups[1].request_items() == [{"start": 4443, "last": 4495}]

    complete = merge_deferred_groups(PAGE, groups, [FRAGMENT_1, FRAGMENT_2])
    assert "339.\u2005§" in complete
    assert "465.\u2005§" in complete
    assert "Keep this exact paragraph." in complete
    assert "Keep the footer." in complete
    assert "§338: available immediately" in complete
    assert not find_deferred_groups(complete)


def test_reject_missing_or_truncated_ajax_response():
    groups = find_deferred_groups(PAGE)
    with pytest.raises(ValueError, match="Not all"):
        merge_deferred_groups(PAGE, groups, [FRAGMENT_1])
    with pytest.raises(ValueError, match="omitted expected"):
        merge_deferred_groups(PAGE, groups, [FRAGMENT_1, "No block IDs here"])


def test_no_blocks_keeps_original_markup():
    ordinary_html = "<main><p>Short complete law</p></main>"
    assert not find_deferred_groups(ordinary_html)
    assert merge_deferred_groups(ordinary_html, [], []) == ordinary_html


@pytest.mark.asyncio
async def test_client_posts_block_ranges_and_returns_complete_text(tmp_path):
    posts: list[dict] = []
    fragments = [FRAGMENT_1, FRAGMENT_2]

    def handle_request(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/ajax/njtGetBlock.json"
        payload = json.loads(request.content)
        posts.append(payload)
        assert payload["documentId"] == "2012-100-00-00"
        return httpx.Response(200, text=fragments[len(posts) - 1])

    client = NjtClient(cache=HttpCache(tmp_path))
    await client._http.aclose()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
    try:
        url = "https://njt.jog.gov.hu/jogszabaly/2012-100-00-00"
        complete = await client.load_complete_text(url, PAGE)
        assert "339.\u2005§" in complete
        assert "465.\u2005§" in complete
        assert len(posts) == 2
        assert posts[0]["data"] == [{"start": 2943}, {"start": 3003, "last": 3062}]
        assert posts[1]["data"] == [{"start": 4443, "last": 4495}]
        assert await client.load_complete_text(url, PAGE) == complete
        assert len(posts) == 2  # full text is cached
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_client_fails_closed_on_missing_blocks(tmp_path):
    def bad_response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<p>Not the requested statute</p>")

    client = NjtClient(cache=HttpCache(tmp_path))
    await client._http.aclose()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(bad_response))
    try:
        with pytest.raises(HuError, match="Could not reconstruct"):
            await client.load_complete_text(
                "https://njt.jog.gov.hu/jogszabaly/2012-100-00-00", PAGE
            )
    finally:
        await client.aclose()


def test_raw_strings_in_text_css_or_scripts_do_not_fail_a_complete_page():
    page = (
        "<style>.pH.borderStart{min-height:2em}</style>"
        "<script>angular.element('.pH.borderStart')</script>"
        "<main><p>A víz pH-értéke 6,5 és 8,5 között legyen.</p></main>"
    )
    assert find_deferred_groups(page) == []


def test_reject_changed_placeholder_markup():
    page = '<div id="x" class="borderStart pHolder" data-show-order="1"></div>'
    with pytest.raises(ValueError, match="not recognized"):
        find_deferred_groups(page)


def test_reject_unclosed_placeholder_even_when_others_parse():
    page = PAGE.replace("</main>", "") + (
        '<div id="sc-btk-4" class="pH borderStart" data-show-order="5000">'
        '<span id="SZ470"></span>'
    )
    with pytest.raises(ValueError, match="Unclosed"):
        find_deferred_groups(page)


def test_reject_placeholder_range_that_would_delete_rendered_text():
    # The inner div is never closed, so the placeholder's own </div> closes the inner
    # one and the placeholder "ends" at the next </div>, swallowing the real section.
    page = (
        "<div class='wrapper'>"
        '<div id="sc-btk-1" class="pH borderStart" data-show-order="2943">'
        '<div class="pH"><span id="SZ339"></span>'
        "</div>"
        "<p>340. § Real, already rendered text</p>"
        "</div>"
    )
    with pytest.raises(ValueError, match="rendered text"):
        find_deferred_groups(page)


def test_block_counts_as_returned_when_its_id_range_comes_back():
    # Seen live for an annex group of 314/2012. Korm. rendelet: NJT returns the content
    # slices of the range but not the outer placeholder id itself.
    page = (
        "<main><p>58. §</p>"
        '<div id="sc2012-314-20-22-2424" class="pH borderStart" data-show-order="729" '
        'data-last-show-order="755"><span id="ME9"></span>'
        '<div id="sc2012-314-20-22-2425" class="pH"></div>'
        '<div id="sc2012-314-20-22-2514" class="pH"></div>'
        "</div></main>"
    )
    fragment = '<div id="sc2012-314-20-22-2433" class="szelet">9. melléklet</div>'
    groups = find_deferred_groups(page)
    assert "9. melléklet" in merge_deferred_groups(page, groups, [fragment])

    unrelated = '<div id="sc2012-314-20-22-9000" class="szelet">other</div>'
    with pytest.raises(ValueError, match="omitted expected"):
        merge_deferred_groups(page, groups, [unrelated])
