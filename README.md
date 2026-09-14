# wikiloc

Parse **in-source locators** from Wikipedia citation wikitext.

An *in-source location* is the specific part of a source that supports a
statement — a page, a page range, a chapter, a quotation.... Editors record
these through dedicated citation-template parameters (`page`, `pages`, `chapter`,
`quote`, …), which we call **locators**. `wikiloc` reads the locators (and
identifiers) declared by references, using the exact set of parameters each
citation template authorises.

- Zero runtime dependencies (Python standard library only) for parsing, optional mwparserfromhell for ref extraction from wikitext.
- English by default; French included but not fully tested; more languages can be added.
- Three levels: a single reference, an article's reference list, or whole-article wikitext.

The parser is regression-tested against a golden set of 160 hand-annotated citations (English Wikipedia, 2014 and 2026 snapshots, stratified by template and locator type) in tests/test_golden.py.
On that set it reaches 100% precision and recall for locator presence and type. Every row also asserts the `page`/`pages` value (when one is expected) and the `compute_located_pages()` count. Four malformed-source citations keep the parser's raw value rather than the human gold; each is documented with a note in the test explaining the mismatch.

## Install

```bash
pip install wikiloc            # core (stdlib only)
pip install wikiloc[extract]   # + whole-article extraction (mwparserfromhell)
```

## Quickstart

**A single reference:**

```python
from wikiloc import parse

parse("{{cite book|title=X|isbn=978-0-13-468599-1|page=42}}")
# {'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {'isbn': '978-0-13-468599-1'}}

parse("<ref name=\"a\">{{cite book|title=B|page=87}}</ref>{{rp|page=92}}")
# {'cite_type': 'cite book', 'locators': {'page': '92'}, 'ids': {}}
```

**A list of references from one article** (resolved with named-reference
inheritance):

```python
parse(["<ref name=a>{{cite book|page=10}}</ref>", "<ref name=a/>{{rp|13}}"])
# second dict: {'cite_type': 'cite book', 'ref_type': 'repeated_rp', 'page': '13', ...}
```

**Whole-article wikitext** (extraction + resolution; needs `[extract]`):

```python
from wikiloc import parse_article

parse_article(article_wikitext)
# [{'ref_type': 'main', 'page': '42', ...}, ...]
```

### Output

`parse()` on a single reference returns:

| key         | meaning                                                              |
|-------------|---------------------------------------------------------------------|
| `cite_type` | normalized template name (e.g. `cite book`) or `None`               |
| `locators`  | in-source locators found, keyed by their literal parameter name     |
| `ids`       | identifiers found (`isbn`, `doi`, `pmid`, `pmc`, `arxiv`)           |
| `ref_key`   | short-cite key for `{{r}}`/`{{sfn}}`/`{{sfnp}}` (only when present)  |

Locators keep their literal parameter key (e.g. `p`, `pp`); canonicalising
aliases onto `page`/`pages` is left to the caller.

### Supported reference forms

`{{cite …}}` / `{{citation}}` (CS1/CS2), `{{rp}}`, `{{r}}`, `{{sfn}}`,
`{{sfnp}}`, Harvard short cites (`{{harvnb}}` and variants), `<ref>…</ref>`
tags (optionally followed by an `{{rp|…}}`), and untemplated (plain-text)
references. For untemplated text, only pages/page-ranges introduced by an
explicit marker (`p.`, `pp.`, `page`, `pages`, `pg`, `pgs`) are read, so years,
scores and dates are not mistaken for page numbers.

### Short-cite (CITEREF) resolution

At article level, `parse()` on a list and `parse_article()` resolve shortened
footnotes (`{{sfn}}`, `{{sfnp}}`, the Harvard family) and `{{r}}` keys against
full CS1/CS2 citations through their HTML anchor: the explicit `|ref=` value or
the auto-generated `CITEREF<last-names><year>` id (built from up to four author
last names — editors when there is no author — plus the year from `|year=` or
`|date=`, mirroring Module:Citation/CS1). A matching short cite inherits the full
citation's `cite_type` and identifiers (`isbn`, `doi`, …), so enrichment follows
the link.

```python
parse_article(
    "Text.{{sfn|Smith|2020|p=3}}\n"
    "<ref>{{cite book|last=Smith|year=2020|isbn=978-0-13-468599-1|pages=100-150}}</ref>"
)
# the sfn record inherits cite_type='cite book', isbn=… and pages='100-150'
```

`|ref=none` disables the anchor, `|ref=harv` forces the auto id, any other
`|ref=` value is the literal id, and `{{sfnref|…}}`/`{{harvid|…}}` expand to
CITEREF ids.


## Flags

`wikiloc.detect_locator_issues(parsed_ref)` returns issue codes for suspicious
or missing locators, to help audit citations. It accepts either a `parse()`
result or a flat locator record:

- `no_locator` — the reference declares no locator at all;
- `pages_single` — a `pages`/`pp` value is a single page number (often a total-page count);
- `page_range` — a `page`/`p` value holds a range or comma list (probably belongs in `pages`);
- `page_unparseable` / `pages_unparseable` — the value could not be parsed;
- `page_huge` — a `page`/`p` number exceeds `PAGE_HUGE_THRESHOLD` (default 99999);
- `pages_range_huge` — a `pages`/`pp` range exceeds `PAGES_RANGE_HUGE_THRESHOLD` (default 999);
- `page_reversed_range` / `pages_reversed_range` — a range runs backwards (`hi < lo`);
- `page_noisy` — a parseable `page`/`p` value also carries prose (e.g. `200–201 & sketch 19`);
- `page_pages_conflict` — `page`/`p` falls outside the `pages`/`pp` range.

Flags are **not** run by default, so `parse()` output stays a faithful
transcription of the source. Opt in with `with_flags=True`:

```python
parse("{{cite book|title=X|pages=240}}", with_flags=True)
# {'cite_type': 'cite book', 'locators': {'pages': '240'}, 'ids': {}, 'flags': ['pages_single']}
```

For a list of references, each resolved record gets its own `flags` key. Thresholds
live in `wikiloc.parser` (`PAGE_HUGE_THRESHOLD`, `PAGES_RANGE_HUGE_THRESHOLD`).


## Located-page counting

`wikiloc.compute_located_pages` turns a reference's `page`/`pages`
locators into a page count. It accepts either a `parse()` result or a flat
locator record.

- a single number counts as **1 page**;
- a `page`/`p` locator counts as **1 page** even if its value is malformed
  (`detect_locator_issues` reports those);
- a range `a–b` counts as `b − a + 1` pages, with abbreviated ends expanded
  (`446–52` → pp. 446–452, 7 pages);
- a reversed range counts as 1;
- a comma-separated list of page numbers counts its items;
- section-style ranges such as `S1–S5` count their members;
- an unparseable `pages`/`pp` value is treated as absent;
- when `page` and `pages` coexist, the **minimum** is used.

Quote/chapter/`at`/`loc` and other non-paginated locators are deliberately
excluded: the package stays unopinionated about how much they narrow a source.

### What the count does not cover

`compute_located_pages` is an estimate, not an exact page count:

- only `page`/`pages` (`p`/`pp`) are counted — a page number buried in an
  `at`/`loc` value (e.g. `at=cc1278-84`) is not;
- a single `pages`/`pp` number counts as **1** page even when it is really a
  total-page count rather than a pin (see the `pages_single` flag);
- malformed values are absorbed, not surfaced: an unparseable `page`/`p` still
  counts as 1, while one bad item in a `pages`/`pp` list drops the whole list
  (treated as absent);
- a reversed range counts as 1;
- when `page` and `pages` coexist, only the minimum is returned;
- Roman numerals are accepted only in the strict 1–4999 grammar (`IIII`, `VX`
  are rejected).

Pair the count with `detect_locator_issues` when these cases matter.


## Extending

The locator vocabulary lives in `wikiloc/constants.py`:

- **New language** — add a `LOC_PARAMS[lang]` mapping of template name → locators.
- **New locator** — append the parameter alias to the relevant template's list.
- **New identifier** — add an alias → canonical mapping in `ID_ALIASES` (and, for
  free-text detection, a pattern in `_extract_ids_from_text`).


## License

MIT License.
