# wikiloc

Parse **in-source locators** from Wikipedia citation wikitext.

An *in-source location* is the specific part of a source that supports a
statement — a page, a page range, a chapter, or a quotation. Editors record
these through dedicated citation-template parameters (`page`, `pages`, `chapter`,
`quote`, …), which we call **locators**. `wikiloc` reads the locators (and
identifiers) declared by a single reference, using the exact set of parameters
each citation template authorises.

Unlike general-purpose citation-extraction pipelines, `wikiloc` focuses narrowly
on in-source locator fields. It is the standalone parser from the study
*"Citation Location Needed"*.

- **Zero runtime dependencies** (Python standard library only).
- English by default; French included; more languages are a data change away.

## Install

```bash
pip install wikiloc          # from a checkout: pip install -e .
```

## Quickstart

Pass the wikitext of a *single* reference — a `<ref>…</ref>` tag, a bare
template, or a plain-text reference:

```python
from wikiloc import parse

parse("{{cite book|title=X|isbn=978-0-13-468599-1|page=42}}")
# {'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {'isbn': '978-0-13-468599-1'}}

parse("{{sfn|Smith|2020|p=42}}")
# {'cite_type': None, 'locators': {'p': '42'}, 'ids': {}, 'ref_key': 'Smith'}

parse("<ref name=\"a\">{{cite book|title=B|page=87}}</ref>{{rp|page=92}}")
# {'cite_type': 'cite book', 'locators': {'page': '92'}, 'ids': {}}

parse("Smith, John (2020). Title. Publisher. p. 41. ISBN 978-950-581-815-0")
# {'cite_type': None, 'locators': {'page': '41'}, 'ids': {'isbn': '978-950-581-815-0'}}
```

### Output

`parse()` returns a dict:

| key         | meaning                                                              |
|-------------|---------------------------------------------------------------------|
| `cite_type` | normalized template name (e.g. `cite book`) or `None`               |
| `locators`  | in-source locators found, keyed by their literal parameter name     |
| `ids`       | identifiers found (`isbn`, `doi`, `pmid`, `pmc`, `arxiv`)           |
| `ref_key`   | short-cite key for `{{r}}`/`{{sfn}}`/`{{sfnp}}` (only when present)  |

Locators keep their literal parameter key (e.g. `p`, `pp`); normalising aliases
onto `page`/`pages` is left to downstream analysis.

### Supported reference forms

`{{cite …}}` / `{{citation}}` (CS1/CS2), `{{rp}}`, `{{r}}`, `{{sfn}}`,
`{{sfnp}}`, Harvard short cites (`{{harvnb}}` and variants), `<ref>…</ref>`
tags (optionally followed by an `{{rp|…}}`), and untemplated (plain-text)
references. For untemplated text, only pages/page-ranges introduced by an
explicit marker (`p.`, `pp.`, `page`, `pages`) are read, so years, scores and
dates are not mistaken for page numbers.

## Extending

The locator vocabulary lives in [`wikiloc/constants.py`](constants.py):

- **New language** — add a `LOC_PARAMS[lang]` mapping of template name → locators.
- **New locator** — append the parameter alias to the relevant template's list.
- **New identifier** — add an alias → canonical mapping in `ID_ALIASES` (and, for
  free-text detection, a pattern in `_extract_ids_from_text`).

## Scope

`wikiloc` parses **one reference at a time**. Extracting references from
whole-article wikitext and reconciling named/repeated references across an
article are intentionally out of scope — pair `parse()` with any reference
extractor for article-scale use.

## License

GNU AGPL v3 or later — see the `LICENSE` file.
