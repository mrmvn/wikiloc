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

The parser is regression-tested against a golden set of 160 hand-annotated citations (English Wikipedia, 2014 and 2026 snapshots, stratified by template and locator type) in tests/test_golden.py. On that set it reaches 100% precision and recall for locator presence and type; four malformed-source citations keep the parser's raw value rather than the human gold and are documented in the test.

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


## Flags

`wikiloc.page_locator_flags(parsed_ref)` returns issue codes for suspicious
page values, to help audit citations. It accepts either a `parse()` result or
a flat locator record:

- `pages_single` — a `pages`/`pp` value is a single page number (often a total-page count);
- `page_range` — a `page`/`p` value holds a range or comma list (probably belongs in `pages`);
- `page_unparseable` / `pages_unparseable` — the value could not be parsed.


## Located-page counting

`wikiloc.compute_located_pages` turns a reference's `page`/`pages`
locators into a page count. It accepts either a `parse()` result or a flat
locator record.

- a single number counts as **1 page**;
- a `page`/`p` locator counts as **1 page** even if its value is malformed
  (`page_locator_flags` reports those);
- a range `a–b` counts as `b − a + 1` pages, with abbreviated ends expanded
  (`446–52` → pp. 446–452, 7 pages);
- a reversed range counts as 1;
- a comma-separated list of page numbers counts its items;
- section-style ranges such as `S1–S5` count their members;
- an unparseable `pages`/`pp` value is treated as absent;
- when `page` and `pages` coexist, the **minimum** is used.

Quote/chapter/`at`/`loc` and other non-paginated locators are deliberately
excluded: the package stays unopinionated about how much they narrow a source.


## Extending

The locator vocabulary lives in `wikiloc/constants.py`:

- **New language** — add a `LOC_PARAMS[lang]` mapping of template name → locators.
- **New locator** — append the parameter alias to the relevant template's list.
- **New identifier** — add an alias → canonical mapping in `ID_ALIASES` (and, for
  free-text detection, a pattern in `_extract_ids_from_text`).


## License

MIT License.
