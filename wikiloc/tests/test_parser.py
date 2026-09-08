"""Standalone tests for the wikiloc parser.

Depends only on the `wikiloc` package (no analysis stack, no data files).
Run with `pytest` or directly: `python -m wikiloc.tests.test_parser`.
"""

from wikiloc import parse
from wikiloc.parser import (
    _extract_template_params,
    _parse_page_range,
    _compute_located_pages,
    _extract_ids_from_text,
    _detect_template_name,
)


# --- Public string-in API: parse() -----------------------------------------

def test_parse_cite_template_string():
    assert parse("{{cite book|title=X|isbn=978-0-13-468599-1|page=42}}") == {
        'cite_type': 'cite book',
        'locators': {'page': '42'},
        'ids': {'isbn': '978-0-13-468599-1'},
    }
    # cite journal: locator + identifier separated; page-not-authorised keys dropped
    assert parse("{{cite journal|title=P|doi=10.1/x|pages=5-9|department=Sci}}") == {
        'cite_type': 'cite journal',
        'locators': {'pages': '5-9', 'department': 'Sci'},
        'ids': {'doi': '10.1/x'},
    }
    # CS2 generic citation template
    assert parse("{{citation|title=Y|pages=100-150}}") == {
        'cite_type': 'citation', 'locators': {'pages': '100-150'}, 'ids': {},
    }


def test_parse_cite_video_game_uses_specific_locators():
    # A2: 'cite video game' must resolve to its own entry (level/scene/quote-*),
    # not the truncated 'cite video' (generic list) — so 'page' is dropped here.
    assert parse("{{cite video game|title=X|level=3|scene=S1|page=99}}") == {
        'cite_type': 'cite video game',
        'locators': {'level': '3', 'scene': 'S1'},
        'ids': {},
    }


def test_detect_template_name_prefers_longest_cite():
    # A2: three-word 'cite ...' templates map to their specific entry.
    assert _detect_template_name("{{cite video game | title=X}}", 'en') == 'cite video game'
    assert _detect_template_name("{{cite AV media | title=X}}", 'en') == 'cite av media'
    # Two-word templates still resolve.
    assert _detect_template_name("{{cite book | title=X}}", 'en') == 'cite book'
    # Unknown two-word templates keep their name (fall back to the generic
    # 'cite' locator list in _parse_cite_template) rather than collapsing.
    assert _detect_template_name("{{cite dnb | title=X}}", 'en') == 'cite dnb'
    assert _detect_template_name("{{cite press release | title=X}}", 'en') == 'cite press'


def test_parse_ref_tag_and_rp_override():
    # A <ref> wrapping a cite template
    assert parse("<ref>{{cite book|title=B|page=87}}</ref>") == {
        'cite_type': 'cite book', 'locators': {'page': '87'}, 'ids': {},
    }
    # A trailing {{rp}} overrides the location (more specific)
    assert parse('<ref name="a">{{cite book|title=B|page=87}}</ref>{{rp|page=92}}') == {
        'cite_type': 'cite book', 'locators': {'page': '92'}, 'ids': {},
    }
    # A self-closing repeated ref carries no locator on its own
    assert parse('<ref name="a" />') == {'cite_type': None, 'locators': {}, 'ids': {}}


def test_parse_short_cites():
    # sfn / sfnp / r expose their short-cite key under ref_key
    assert parse("{{sfn|Smith|2020|p=42}}") == {
        'cite_type': None, 'locators': {'p': '42'}, 'ids': {}, 'ref_key': 'Smith',
    }
    # Locators keep their literal param key ('pp' here); alias-normalisation to
    # page/pages is an analysis-side concern, not the parser's.
    assert parse("{{sfnp|Smith|2020|pp=42-45}}") == {
        'cite_type': None, 'locators': {'pp': '42-45'}, 'ids': {}, 'ref_key': 'Smith',
    }
    assert parse("{{r|Smith2020|page=7}}") == {
        'cite_type': None, 'locators': {'page': '7'}, 'ids': {}, 'ref_key': 'Smith2020',
    }
    # Harvard variants collapse to cite_type 'harv'
    assert parse("{{harvnb|Jones|2019|p=3}}")['cite_type'] == 'harv'


def test_parse_standalone_rp():
    # Positional range -> pages; explicit page= -> page
    assert parse("{{rp|59–60}}") == {'cite_type': None, 'locators': {'pages': '59–60'}, 'ids': {}}
    assert parse("{{rp|page=42}}") == {'cite_type': None, 'locators': {'page': '42'}, 'ids': {}}


def test_parse_untemplated_separates_ids():
    assert parse("Smith, John (2020). Title. Publisher. p. 41. ISBN 978-950-581-815-0") == {
        'cite_type': None, 'locators': {'page': '41'}, 'ids': {'isbn': '978-950-581-815-0'},
    }
    # Bare year/score ranges are not mistaken for page numbers
    assert parse("The Kent League 1894–1930") == {'cite_type': None, 'locators': {}, 'ids': {}}


def test_parse_fr_cite_report_locators():
    # A3: the French 'cite report' key is lowercase and 'page' is spelled
    # correctly (was the capital-C 'Cite report' and the 'pasge' typo).
    assert parse("{{cite report|titre=X|page=5}}", 'fr') == {
        'cite_type': 'cite report',
        'locators': {'page': '5'},
        'ids': {},
    }
    # Capitalised template name is normalised too.
    assert parse("{{Cite report|titre=X|pages=12-14|page=5}}", 'fr') == {
        'cite_type': 'cite report',
        'locators': {'pages': '12-14', 'page': '5'},
        'ids': {},
    }


# --- Helper coverage (used by the pipeline and public API) ------------------

def test_extract_template_params():
    assert _extract_template_params("{{cite web|title=Example|page=42}}") == {
        'title': 'Example', 'page': '42'}
    # Nested braces don't break pipe splitting
    assert _extract_template_params("{{cite book|author=Smith|quote=A {{nested}} template}}") == {
        'author': 'Smith', 'quote': 'A {{nested}} template'}


def test_parse_page_range():
    assert _parse_page_range("42") == 1
    assert _parse_page_range("100-150") == 51
    assert _parse_page_range("100–150") == 51
    assert _parse_page_range("100, 105, 110") == 3
    assert _parse_page_range("S100-S105") == 6
    assert _parse_page_range("vi") is None
    assert _parse_page_range("") is None


def test_compute_located_pages():
    assert _compute_located_pages({'page': '42'}) == 1
    assert _compute_located_pages({'pages': '100-150'}) == 51
    assert _compute_located_pages({'quote': 'text'}) == 1
    # tightest wins when several locators coexist
    assert _compute_located_pages({'pages': '100-150', 'quote': 'text'}) == 1
    assert _compute_located_pages({'cite_type': 'cite book'}) is None


def test_extract_ids_from_text():
    assert _extract_ids_from_text("Chin, John. Title. ISBN 978-1-5381-2068-2") == {
        'isbn': '978-1-5381-2068-2'}
    assert _extract_ids_from_text("See {{doi|10.1038/nature12373}}") == {
        'doi': '10.1038/nature12373'}
    assert _extract_ids_from_text("Just a plain reference") == {}


if __name__ == '__main__':
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
    sys.exit(0)
