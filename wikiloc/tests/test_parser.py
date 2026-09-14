"""Standalone tests for the wikiloc parser.

Depends only on the `wikiloc` package (no analysis stack, no data files).
Run with `pytest` or directly: `python -m wikiloc.tests.test_parser`.
"""

import pytest

from wikiloc import parse
from wikiloc.parser import (
    _extract_template_params,
    _parse_page_range,
    _range_bounds,
    _page_count_of_item,
    compute_located_pages,
    _extract_ids_from_text,
    _detect_template_name,
    detect_locator_issues,
    is_templated_ref,
    resolve_references,
    which_cite_template,
    _cs1_anchor_from_params,
    _ref_anchor_keys,
    _short_cite_anchor_keys,
    _ref_from_wikitext,
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
    # Roman numerals are now valid page tokens (R1).
    assert _parse_page_range("vi") == 1
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


def test_detect_locator_issues():
    assert detect_locator_issues({'pages': '240'}) == ['pages_single']
    assert detect_locator_issues({'page': '100-150'}) == ['page_range']
    assert detect_locator_issues({'page': '25, [url] 29'}) == ['page_unparseable']
    assert detect_locator_issues({'page': 'pages 32'}) == ['page_unparseable']
    assert detect_locator_issues({'pages': '4B}}{{Open Access'}) == ['pages_unparseable']
    assert detect_locator_issues({'page': '42'}) == []
    assert detect_locator_issues({'pages': '100-150'}) == []
    assert detect_locator_issues({'pages': 'S1-S5'}) == []


def test_detect_locator_issues_grouped():
    # accepts the grouped parse() output
    assert detect_locator_issues(parse("{{cite book|title=X|page=ff42xx,44}}")) == ['page_unparseable']
    assert detect_locator_issues(parse("{{cite book|title=X|pages=240}}")) == ['pages_single']
    assert detect_locator_issues(parse("{{cite book|title=X|page=42}}")) == []


def test_detect_locator_issues_no_locator():
    # grouped result with only a title -> no locator
    assert detect_locator_issues(parse("{{cite book|title=X}}")) == ['no_locator']
    # flat record: cite/ref metadata and ids are not locators
    assert detect_locator_issues({'cite_type': 'cite book', 'isbn': '978-0-13-468599-1'}) == ['no_locator']
    assert detect_locator_issues({'ref_type': 'repeated', 'ref_name': 'x'}) == ['no_locator']
    assert detect_locator_issues({'quote': 'hi'}) == []


def test_detect_locator_issues_reversed_ranges():
    assert 'page_reversed_range' in detect_locator_issues({'page': '150-100'})
    assert 'pages_reversed_range' in detect_locator_issues({'pages': '150-100'})
    assert 'page_reversed_range' in detect_locator_issues({'page': 'S5-S1'})
    # forward and abbreviated ranges are not reversed
    assert 'page_reversed_range' not in detect_locator_issues({'page': '100-150'})
    assert 'page_reversed_range' not in detect_locator_issues({'page': '446-52'})


def test_detect_locator_issues_huge():
    assert 'page_huge' in detect_locator_issues({'page': '100000'})
    assert 'page_huge' in detect_locator_issues({'page': '100000-100005'})
    assert 'page_huge' not in detect_locator_issues({'page': '99999'})
    assert 'pages_range_huge' in detect_locator_issues({'pages': '1-2000'})
    assert 'pages_range_huge' not in detect_locator_issues({'pages': '1-999'})


def test_detect_locator_issues_huge_seven_digits():
    # no digit cap: 7+ digit values parse (counting as one page) and are flagged
    # huge, rather than being reported as unparseable.
    assert detect_locator_issues({'page': '1000000'}) == ['page_huge']
    assert detect_locator_issues({'page': '12345678'}) == ['page_huge']
    assert 'page_unparseable' not in detect_locator_issues({'page': '1000000'})
    assert _parse_page_range('1000000') == 1


def test_range_bounds_do_not_truncate():
    # long endpoints are consumed whole (previously 1-1000000 matched 1-100000)
    assert _range_bounds('1-1000000') == (1, 1000000)
    assert _parse_page_range('1-1000000') == 1000000
    flags = detect_locator_issues({'page': '1-1000000'})
    assert 'page_huge' in flags and 'page_unparseable' not in flags


def test_detect_locator_issues_noisy():
    flags = detect_locator_issues({'page': '200–201 & sketch 19'})
    assert 'page_noisy' in flags and 'page_range' in flags
    assert 'page_noisy' not in detect_locator_issues({'page': '200–201'})
    assert 'page_noisy' not in detect_locator_issues({'page': '100, 105, 110'})


def test_detect_locator_issues_conflict():
    assert detect_locator_issues({'page': '50', 'pages': '100-150'}) == ['page_pages_conflict']
    assert detect_locator_issues({'page': '120', 'pages': '100-150'}) == []
    assert 'page_pages_conflict' not in detect_locator_issues({'page': '100-120', 'pages': '100-150'})
    # a single pages number is a total-page count, not a range to conflict with
    assert detect_locator_issues({'page': '50', 'pages': '240'}) == ['pages_single']


def test_parse_with_flags():
    result = parse("{{cite book|title=X|pages=1-2000}}", with_flags=True)
    assert result['locators'] == {'pages': '1-2000'}
    assert result['flags'] == ['pages_range_huge']
    # default output stays flag-free
    assert 'flags' not in parse("{{cite book|title=X|page=42}}")
    # list overload annotates every resolved record
    resolved = parse([
        '<ref name="x">{{cite book|title=X}}</ref>',
        '<ref name="x"/>',
    ], with_flags=True)
    assert resolved[0]['flags'] == ['no_locator']
    assert resolved[1]['flags'] == ['no_locator']


def testcompute_located_pages_grouped():
    assert compute_located_pages(parse("{{cite book|page=42}}")) == 1
    assert compute_located_pages(parse("{{cite book|pages=100-150}}")) == 51
    assert compute_located_pages(parse("{{cite book|quote=hi}}")) is None


def test_parse_page_range_garbage():
    assert _parse_page_range("ff42xx,44") is None
    assert _parse_page_range("25, [url] 29") is None
    assert _parse_page_range("A01, A04") == 2


def testcompute_located_pages():
    assert compute_located_pages({'page': '42'}) == 1
    assert compute_located_pages({'pages': '100-150'}) == 51
    # non-paginated locators (quote/chapter/at) are deliberately excluded
    assert compute_located_pages({'quote': 'text'}) is None
    assert compute_located_pages({'chapter': 'Intro'}) is None
    # when pages and a quote coexist, the page range wins (no quote->1 floor)
    assert compute_located_pages({'pages': '100-150', 'quote': 'text'}) == 51
    assert compute_located_pages({'cite_type': 'cite book'}) is None


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


# --- WL-1: trailing text around a leading template ------------------------

def test_parse_template_with_trailing_text():
    # trailing punctuation no longer defeats templated-ref detection
    assert parse("{{cite book|title=X|page=42}}.") == {
        'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {}}
    assert parse("<ref>{{cite book|title=X|page=42}}.</ref>") == {
        'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {}}
    # a leading HTML comment is transparent too
    assert parse("<ref><!-- note -->{{cite book|title=X|page=42}}</ref>") == {
        'cite_type': 'cite book', 'locators': {'page': '42'}, 'ids': {}}
    # trailing prose / language annotation
    assert parse("<ref>{{cite book|title=X|page=42}} (in French)</ref>")['locators'] == {'page': '42'}


def test_parse_template_trailing_fallback_and_precedence():
    # template declares no locator -> a plain-text marker in the trailing text wins
    assert parse("<ref>{{cite web|title=X}} See p. 5.</ref>") == {
        'cite_type': 'cite web', 'locators': {'page': '5'}, 'ids': {}}
    # template declares a locator -> the template wins over the trailing marker
    assert parse("<ref>{{cite web|title=X|page=3}} See p. 5.</ref>") == {
        'cite_type': 'cite web', 'locators': {'page': '3'}, 'ids': {}}


def test_parse_untemplated_regression():
    # genuine free text (no leading template) still parses as before
    assert parse("Smith, John (2020). Title. Publisher. p. 42") == {
        'cite_type': None, 'locators': {'page': '42'}, 'ids': {}}


# --- WL-3: short-cite template wrapped in <ref> ---------------------------

def test_parse_short_cite_wrapped_in_ref():
    assert parse("<ref>{{sfn|Smith|2020|p=42}}</ref>") == {
        'cite_type': None, 'locators': {'p': '42'}, 'ids': {}, 'ref_key': 'Smith'}
    assert parse("<ref>{{sfnp|Smith|2020|pp=42-45}}</ref>") == {
        'cite_type': None, 'locators': {'pp': '42-45'}, 'ids': {}, 'ref_key': 'Smith'}
    assert parse("<ref>{{r|Smith2020|page=7}}</ref>") == {
        'cite_type': None, 'locators': {'page': '7'}, 'ids': {}, 'ref_key': 'Smith2020'}
    # Harvard variants already resolved inside <ref>; keep them working
    assert parse("<ref>{{harvp|Jones|2019|p=3}}</ref>")['cite_type'] == 'harv'
    # a stray {{rp}} inside a <ref> yields its page
    assert parse("<ref>{{rp|59-60}}</ref>")['locators'] == {'pages': '59-60'}


# --- WL-4: page lists mixing single numbers and ranges --------------------

def test_parse_page_range_mixed_list():
    assert _parse_page_range("21, 31, 56-57") == 4
    assert _parse_page_range("21, 31, 56\u201357") == 4
    assert _parse_page_range("5, 7-9") == 4
    assert _parse_page_range("S1, S3-S5") == 4
    # all-singles list unchanged
    assert _parse_page_range("100, 105, 110") == 3
    # stray trailing comma behaves as before
    assert _parse_page_range("21,") == 1
    # malformed list stays unparseable
    assert _parse_page_range("21, foo") is None


def test_detect_and_count_mixed_page_list():
    assert detect_locator_issues({'cite_type': 'cite book', 'pages': '21, 31, 56-57'}) == []
    assert compute_located_pages({'pages': '21, 31, 56-57'}) == 4
    # a mixed list under page/p is still flagged as a range/list
    assert detect_locator_issues({'page': '21, 31, 56-57'}) == ['page_range']
    assert detect_locator_issues({'pages': '21, foo'}) == ['pages_unparseable']


# --- Roman numerals (R1) ---------------------------------------------------

def test_parse_page_range_roman_golden():
    # Golden cases: single, en-dash range, and a range whose count is 2.
    assert _parse_page_range('xiv') == 1
    assert _parse_page_range('iv\u2013viii') == 5  # 4..8 inclusive
    assert _parse_page_range('xxvii\u2013xxviii') == 2  # 27..28 inclusive
    # ASCII hyphen and case-insensitivity work the same way.
    assert _parse_page_range('iv-viii') == 5
    assert _parse_page_range('XIV') == 1
    # Mixed roman lists reuse the same item counter.
    assert _parse_page_range('iv, vi\u2013viii') == 4  # 1 + (8 - 6 + 1)
    assert _range_bounds('iv\u2013viii') == (4, 8)


def test_parse_page_range_roman_strict_validation():
    # Malformed numerals must stay unparseable rather than be half-matched.
    assert _parse_page_range('IIII') is None
    assert _parse_page_range('VX') is None
    assert _parse_page_range('foo, iv') is None
    assert _page_count_of_item('') is None


def test_detect_issues_roman():
    # A roman range under page/p is a range, not garbage or prose.
    assert detect_locator_issues({'page': 'iv\u2013viii'}) == ['page_range']
    assert detect_locator_issues({'page': 'xiv'}) == []
    assert detect_locator_issues({'pages': 'xiv'}) == ['pages_single']
    assert compute_located_pages({'pages': 'iv\u2013viii'}) == 5


# --- WL-5: generic fallback for unknown French templates ------------------

def test_parse_fr_unknown_template_fallback():
    assert parse("{{OuvrageX|titre=X|page=42}}", 'fr') == {
        'cite_type': 'ouvragex', 'locators': {'page': '42'}, 'ids': {}}
    assert parse("{{Lien web inconnu|url=X|passage=3}}", 'fr')['locators'] == {'passage': '3'}
    # English generic fallback is unchanged
    assert parse("{{cite dnb|title=X|page=42}}", 'en')['locators'] == {'page': '42'}


# --- WL-8: helper annotations and dead-code behaviour ---------------------

def test_templated_ref_and_which_cite_template_helpers():
    assert is_templated_ref("{{cite book}}") is True
    assert is_templated_ref("{{cite book}}.") is False
    assert is_templated_ref("") is False
    assert which_cite_template("{{ cite journal |title=X}}") == 'cite journal'
    assert which_cite_template("{{cite AV media notes|title=X}}") == 'cite av media notes'
    assert which_cite_template("{{sfn|X}}") is None


# --- WL-6: comment between </ref> and {{rp}} ------------------------------

def test_extract_rp_adjacency_comment():
    pytest.importorskip("mwparserfromhell")
    from wikiloc.extract import extract_references
    # an HTML comment between </ref> and {{rp}} is transparent
    refs = extract_references("<ref>{{cite book|title=X}}</ref><!-- c -->{{rp|13}}")
    assert refs[0]['ref_kind'] == 'ref_tag+rp'
    assert refs[0]['ref_rp_raw'] == '{{rp|13}}'
    # whitespace only still works
    refs = extract_references("<ref>{{cite book|title=X}}</ref>   {{rp|13}}")
    assert refs[0]['ref_kind'] == 'ref_tag+rp'
    # real inline text still breaks the adjacency (regression guard)
    refs = extract_references("<ref>{{cite book|title=X}}</ref> some text {{rp|13}}")
    assert refs[0]['ref_kind'] == 'ref_tag'
    # end to end: the override is applied through resolution
    resolved = resolve_references(refs=extract_references(
        "<ref name=a>{{cite book|title=X}}</ref><!-- c -->{{rp|13}}"))
    assert resolved[0]['page'] == '13'


# --- CS1 anchor (CITEREF) helpers -----------------------------------------

def test_cs1_anchor_from_params_auto_and_explicit():
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|last=Smith|year=2020}}")
    ) == "CITEREFSmith2020"
    # |ref=harv forces the auto anchor
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|last=Smith|year=2020|ref=harv}}")
    ) == "CITEREFSmith2020"
    # |ref=none disables the anchor
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|last=Smith|year=2020|ref=none}}")
    ) is None
    # any other |ref= value is the literal anchor
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|title=No author|ref=Smith2020}}")
    ) == "Smith2020"


def test_cs1_anchor_from_params_date_and_editor():
    # year is taken from |date= when |year= is absent
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|last=Smith|date=2020-03-04}}")
    ) == "CITEREFSmith2020"
    # editors are used when there is no author
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|editor-last=Smith|year=2020}}")
    ) == "CITEREFSmith2020"
    # up to four author last names are concatenated
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|last1=Smith|last2=Jones|year=2020}}")
    ) == "CITEREFSmithJones2020"


def test_cs1_anchor_from_params_sfnref():
    assert _cs1_anchor_from_params(
        _extract_template_params("{{cite book|title=Title|date=1999|ref={{sfnref|Title|1999}}}}")
    ) == "CITEREFTitle1999"


def test_ref_anchor_keys():
    ref = _ref_from_wikitext("<ref>{{cite book|last=Smith|year=2020|isbn=1}}</ref>")
    assert _ref_anchor_keys(ref) == ["CITEREFSmith2020"]
    # no author/editor and no |ref= -> no anchor
    ref = _ref_from_wikitext("<ref>{{cite book|title=No author}}</ref>")
    assert _ref_anchor_keys(ref) == []
    ref = _ref_from_wikitext("<ref>{{cite book|last=Smith|year=2020|ref=none}}</ref>")
    assert _ref_anchor_keys(ref) == []


def test_short_cite_anchor_keys():
    assert _short_cite_anchor_keys(
        _ref_from_wikitext("{{sfn|Smith|2020|p=3}}")
    ) == ["CITEREFSmith2020"]
    assert _short_cite_anchor_keys(
        _ref_from_wikitext("{{harvnb|Smith|Jones|2020|p=3}}")
    ) == ["CITEREFSmithJones2020"]
    assert _short_cite_anchor_keys(
        _ref_from_wikitext("{{r|Smith2020}}")
    ) == ["Smith2020"]


if __name__ == '__main__':
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in fns:
        fn()
        print(f"✓ {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
    sys.exit(0)
