"""Known failure regressions on labelled TEST DATA, not research evaluation labels."""
import pytest
from app.api.search import SearchInput
from app.database.models import Source
from test_retrieval import searcher, indexed


@pytest.mark.parametrize('mode', ['keyword', 'hybrid', 'hybrid_contextual'])
def test_guidelines_typo_is_visible_and_not_dominated_by_fp_certificates(searcher, mode):
    indexed(searcher, 1, ['TEST DATA certificate for successful FP completion.'])
    expected = indexed(searcher, 2, ['TEST DATA guidelines for FP submission, evaluation and required report format.'])
    with searcher.sessions.begin() as session:
        session.get(Source, expected).title = 'TEST DATA Guidelines for FP'
    response = searcher.search(SearchInput(query='guideliness of fp', mode=mode))
    assert response['query_analysis']['corrections'] == [{'from': 'guideliness', 'to': 'guidelines'}]
    assert response['results'][0]['source_id'] == expected
    exact = searcher.search(SearchInput(query='guideliness of fp', mode=mode, correct_spelling=False))
    assert exact['query_analysis']['corrections'] == []


@pytest.mark.parametrize('mode', ['keyword', 'semantic', 'hybrid'])
def test_balanced_candidates_find_sources_after_a_long_document(searcher, mode):
    first = indexed(searcher, 1, ['TEST DATA solar power'] * 70)
    second = indexed(searcher, 2, ['TEST DATA solar power'])
    result = searcher.search(SearchInput(query='solar power', mode=mode))
    assert [hit['source_id'] for hit in result['results']] == [first, second]
    searcher.settings = searcher.settings.model_copy(update={'retrieval_profile': 'classic'})
    classic = searcher.search(SearchInput(query='solar power', mode=mode))
    assert [hit['source_id'] for hit in classic['results']] == [first]


def test_correction_does_not_guess_short_acronyms_or_ambiguous_words(searcher):
    indexed(searcher, 1, ['TEST DATA fp abc metal medal guidelines'])
    response = searcher.search(SearchInput(query='fpp medall', mode='keyword'))
    assert all(row['from'] != 'fpp' for row in response['query_analysis']['corrections'])
    assert searcher.search(SearchInput(query='!!!', mode='keyword'))['query_analysis']['corrections'] == []
