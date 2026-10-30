# Changelog

## 0.3.4 (unreleased)

- Fix `hu_get_text` silently returning truncated legislation when NJT defers
  sections and annexes behind AJAX block placeholders. The new implementation
  fetches missing blocks, reconstructs their original order, and fails closed
  rather than reporting incomplete text as a complete statute.
- Document reproducible cases: Criminal Code (26 deferred blocks), Civil Code
  (78 deferred blocks), and the Debrecen building regulation (2 deferred annex blocks).
- Add offline regression tests and live smoke tests for missing legal text.
- Harden placeholder detection: recognise changed markup from `div` class
  attributes only (not from the raw strings `pH`/`borderStart` anywhere in the
  page), and fail on unclosed placeholders or placeholder ranges containing
  rendered text instead of silently skipping or deleting legal text.
- Warn in the `hu_get_text` description that results can be about 3 MB and may be
  truncated by the client.
- Clarify that NJT's `/ajax/njtGetBlock.json` is undocumented frontend plumbing,
  not a stable public REST API.

Note: the Claude plugin manifest and its `uv.lock` remain pinned to the
previously released 0.3.3 runtime until a 0.3.4 package is published and
the plugin lock can be regenerated against that published release.
