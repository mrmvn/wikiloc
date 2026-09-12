"""Standalone tests for the wikiloc parser.

Depends only on the `wikiloc` package (no analysis stack, no data files).
Run with `pytest` or directly: `python -m wikiloc.tests.test_parser`.
"""

import pytest

from wikiloc import parse
from wikiloc.parser import (
    _extract_template_params,
    _parse_page_range,
    _compute_located_pages,
    _extract_ids_from_text,
    _detect_template_name,
    page_locator_flags,
    resolve_references,
)


# --- Public string-in API: parse() -----------------------------------------

def test_parse_cite_template_string():
    assert parse("{{cite book|title=X|isbn=978-0-13-468599-1|page=42}}") == {
        'cite_type': 'cite book',
        'locators': {'page': '42'},
        'ids': {'isbn': '978-0-13-468599-1'},
    }
    # cite journal: locator + identifier separated; non-locator keys (department) dropped
    assert parse("{{cite journal|title=P|doi=10.1/x|pages=5-9|department=Sci}}") == {
        'cite_type': 'cite journal',
        'locators': {'pages': '5-9'},
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

def test_rp_quote_aliases():
    # A18: Template:Rp supports quote aliases; the parser must not drop them.
    assert parse("<ref>{{cite book|title=X}}</ref>{{rp|quote=long quote}}") == {
        'cite_type': 'cite book', 'locators': {'quote': 'long quote'}, 'ids': {},
    }


def test_resolve_references_inheritance():
    refs = [
        {'ref_kind': 'ref_tag', 'ref_self_closing': False, 'ref_name': 'smith2020',
         'ref_contents': '{{cite book|author=Smith|title=A Book|page=87}}', 'ref_rp_raw': None},
        {'ref_kind': 'ref_tag', 'ref_self_closing': True, 'ref_name': 'smith2020',
         'ref_contents': '', 'ref_rp_raw': None},
    ]
    resolved = resolve_references(refs)
    assert resolved[0]['ref_type'] == 'main'
    assert resolved[0]['page'] == '87'
    assert resolved[1]['ref_type'] == 'repeated'
    assert resolved[1]['cite_type'] == 'cite book'
    assert resolved[1]['page'] == '87'   # inherited from the main definition


def test_resolve_references_rp_override():
    refs = [
        {'ref_kind': 'ref_tag', 'ref_self_closing': False, 'ref_name': 'smith2020',
         'ref_contents': '{{cite book|title=A Book|page=87}}', 'ref_rp_raw': None},
        {'ref_kind': 'ref_tag+rp', 'ref_self_closing': True, 'ref_name': 'smith2020',
         'ref_contents': '', 'ref_rp_raw': '{{rp|page=92}}'},
    ]
    resolved = resolve_references(refs)
    assert resolved[1]['ref_type'] == 'repeated_rp'
    assert resolved[1]['cite_type'] == 'cite book'   # inherited
    assert resolved[1]['page'] == '92'               # rp overrides the page


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


def test_parse_page_range_abbreviated():
    # abbreviated second number shares the leading digits of the first
    assert _parse_page_range("446–52") == 7
    assert _parse_page_range("369-76") == 8
    assert _parse_page_range("142–3") == 2
    # unchanged behaviour
    assert _parse_page_range("100-150") == 51
    assert _parse_page_range("150-100") == 1


def test_untemplated_pg_and_long_page():
    # 'pg' marker and 5-digit single page numbers are recognised
    assert parse("Jon Jørgensen, ''History of the Human Sciences'', vol. 27 no. 3, pg 45") == {
        'cite_type': None, 'locators': {'page': '45'}, 'ids': {},
    }
    assert parse("''Keesing's Contemporary Archives 1950–1952'', page 11076") == {
        'cite_type': None, 'locators': {'page': '11076'}, 'ids': {},
    }


def test_removed_non_locator_keywords():
    # department / season / series-no are not in-source locators
    assert parse("{{cite news|title=X|department=Sports|page=5}}") == {
        'cite_type': 'cite news', 'locators': {'page': '5'}, 'ids': {},
    }
    assert parse("{{cite web|title=X|department=Foo}}") == {
        'cite_type': 'cite web', 'locators': {}, 'ids': {},
    }
    assert parse("{{cite episode|title=X|season=2|series-no=3|time=10:00}}") == {
        'cite_type': 'cite episode', 'locators': {'time': '10:00'}, 'ids': {},
    }


def test_page_locator_flags():
    assert page_locator_flags({'pages': '240'}) == ['pages_single']
    assert page_locator_flags({'page': '100-150'}) == ['page_range']
    assert page_locator_flags({'page': '25, [url] 29'}) == ['page_range']
    assert page_locator_flags({'page': 'pages 32'}) == ['page_unparseable']
    assert page_locator_flags({'pages': '4B}}{{Open Access'}) == ['pages_unparseable']
    assert page_locator_flags({'page': '42'}) == []
    assert page_locator_flags({'pages': '100-150'}) == []
    assert page_locator_flags({'pages': 'S1-S5'}) == []


def test_compute_located_pages():
    assert _compute_located_pages({'page': '42'}) == 1
    assert _compute_located_pages({'pages': '100-150'}) == 51
    # non-paginated locators (quote/chapter/at) are deliberately excluded
    assert _compute_located_pages({'quote': 'text'}) is None
    assert _compute_located_pages({'chapter': 'Intro'}) is None
    # when pages and a quote coexist, the page range wins (no quote->1 floor)
    assert _compute_located_pages({'pages': '100-150', 'quote': 'text'}) == 51
    assert _compute_located_pages({'cite_type': 'cite book'}) is None


def test_extract_ids_from_text():
    assert _extract_ids_from_text("Chin, John. Title. ISBN 978-1-5381-2068-2") == {
        'isbn': '978-1-5381-2068-2'}
    assert _extract_ids_from_text("See {{doi|10.1038/nature12373}}") == {
        'doi': '10.1038/nature12373'}
    assert _extract_ids_from_text("Just a plain reference") == {}


def test_parse_list_overload():
    # a list of reference strings is resolved with name inheritance
    resolved = parse([
        '<ref name="x">{{cite book|page=10}}</ref>',
        '<ref name="x"/>{{rp|13}}',
    ])
    assert isinstance(resolved, list)
    assert resolved[0]['page'] == '10'
    assert resolved[1]['cite_type'] == 'cite book'   # inherited
    assert resolved[1]['page'] == '13'                # rp overrides


def test_parse_article_end_to_end():
    mwparserfromhell = pytest.importorskip("mwparserfromhell")  # noqa: F841
    from wikiloc import parse_article
    art = ('<ref name="x">{{cite book|title=A|page=10}}</ref>\n'
           '<ref name="x"/>\n'
           '{{sfn|Smith|2020|p=42}}')
    resolved = parse_article(art)
    assert len(resolved) == 3
    assert resolved[0]['ref_type'] == 'main' and resolved[0]['page'] == '10'
    assert resolved[1]['ref_type'] == 'repeated' and resolved[1]['page'] == '10'  # inherited
    assert resolved[2]['ref_type'] == 'sfn' and resolved[2]['p'] == '42'


if __name__ == '__main__':
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
    sys.exit(0)
