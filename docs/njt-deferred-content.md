# NJT deferred legal text: reproducible investigation

Verified against `njt.jog.gov.hu` on **2026-10-30**.

## Problem

Hungarian national ELI URLs resolve, but the initial HTML returned by NJT does
**not always contain the complete text**. The browser uses an undocumented AJAX
endpoint to populate empty placeholders when the reader scrolls.

Consequently, a successful HTTP 200 response and a large HTML byte count are
**not evidence of completeness**. References to later sections may occur in
footnotes even when the actual later sections are absent.

The explicit HTML ELI variant `https://njt.jog.gov.hu/eli/TV/2012/100/hu/html`
also redirects to the same partially populated document page.

## Three live examples

| NJT URL | Initial response | Missing content | Supplemental POST response |
| --- | --- | --- | --- |
| [Criminal Code (Btk., Act C of 2012)](https://njt.jog.gov.hu/eli/TV/2012/100) | 1,189,169 bytes; real section text stops at §338 | 26 blocks, starting at §339 | 415,907 bytes; includes §465 |
| [Civil Code (Ptk., Act V of 2013)](https://njt.jog.gov.hu/eli/TV/2013/5) | 1,454,030 bytes; initial HTML has 538 section markers and reaches 4:69. § | 78 blocks | 1,411,768 bytes |
| [Debrecen municipal building regulation, decree 47/2020 (XII.28.)](https://njt.jog.gov.hu/jogszabaly/2020-47-SP-5Y1578.72) | 1,043,349 bytes; includes §137 | 2 *annex* blocks | 527,575 bytes |

The Debrecen local decree is **not currently exposed by this project's ELI tool**;
it is included to show that the underlying NJT behavior also affects local
legislation and annexes, not just long national Acts.

## How to reproduce

1. Fetch `https://njt.jog.gov.hu/eli/TV/2012/100` and follow its redirect to
   `/jogszabaly/2012-100-00-00`.
2. Search for a real statutory section marker such as
   `<span class="szakasz-jel">339. §`. It is **not present** in the initial HTML.
   An occurrence of `339. §` in an amendment footnote is not sufficient.
3. Locate the empty section placeholder:

   ```html
   <div id="sc2012-100-00-00-6581" class="pH borderStart"
        data-show-order="2943" data-b-n="1">
     <div id="sc2012-100-00-00-6583" class="pH" data-b-n="1">
       <span id="SZ339"></span>
     </div>
   </div>
   ```

4. POST the block range to NJT's **undocumented frontend endpoint**:

   ```bash
   curl -sS 'https://njt.jog.gov.hu/ajax/njtGetBlock.json' \
     -H 'Content-Type: application/json' \
     -H 'Accept: text/html' \
     --data '{"documentId":"2012-100-00-00","data":[{"start":2943}]}'
   ```

   Response includes the actual §339 text, beginning with the heading
   *Garázdaság*. The response is HTML despite the `.json` URL suffix.

5. Other placeholder containers carry `data-show-order` and optionally
   `data-last-show-order`. A batch request can supply multiple ranges in the
   `data` array, for example:

   ```json
   {
     "documentId": "2012-100-00-00",
     "data": [
       {"start": 2943},
       {"start": 3003},
       {"start": 4443, "last": 4495}
     ]
   }
   ```

   In the live tests, **all 26 Btk. blocks** and **all 78 Ptk. blocks** could
   each be retrieved in a single batched request. No authenticated session
   cookie was required for the tested requests.

## Implementation and safety considerations

- Only `hu_get_text` needs the full-document reconstruction; metadata retrieval
  can use the initial HTML.
- Parse actual `div.pH.borderStart` placeholders; do not infer completeness
  from document size, a `200 OK` response, footnotes, or generic `§` matches.
- Request the marked show-order ranges and preserve their original position
  when inserting the returned HTML, including interspersed already-loaded text.
- The client sends one request per run of adjacent placeholders, so a document
  whose placeholders are interleaved with already-rendered text needs several
  requests even though the endpoint accepts many ranges at once.
- Validate that every requested block identifier is present in the returned
  HTML. On a missing/failed block, **fail rather than return a purported full text**.
- Also fail when a placeholder is never closed, when a computed placeholder range
  contains rendered text (unbalanced HTML would otherwise make the replacement
  delete real legal text), or when a `div` carries `borderStart` without the known
  `pH borderStart` form. Only `div` class attributes are inspected, so the strings
  `pH` or `borderStart` in legal text, CSS or scripts do not trigger a failure.
- Treat `/ajax/njtGetBlock.json` as an internal, *undocumented* interface;
  its behavior may change. It should not be described as a stable public
  legal-data API.
- ELI identification and machine-accessible full texts are related but distinct:
  this finding does not by itself establish a formal ELI conformance violation.

Offline regression tests use synthetic HTML rather than storing entire statutes
in the repository. Live smoke tests exercise national Acts and the municipal
annex example.
