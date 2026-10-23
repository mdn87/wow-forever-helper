"""Synthetic dependency graphs and saved observations, never a copied quest database."""

from copy import deepcopy
import pytest

from wow_helper.chat import ChatError
from wow_helper.quest_chain import normalize_chain, annotate_chain, chain_text

CHAIN = {'edition': 'Classic Forever beta', 'summary': 'Synthetic chain', 'caveats': [], 'nodes': [
    {'id': 101, 'title': 'Example prerequisite', 'requires': [], 'relation': 'all',
     'sources': ['https://example.com/prerequisite']},
    {'id': 102, 'title': 'Example quest', 'requires': [101], 'relation': 'all',
     'sources': ['https://example.com/quest']},
    {'id': 103, 'title': 'Example follow-up', 'requires': [102, 104], 'relation': 'unknown', 'sources': []},
]}


def test_observations_remain_separate_from_sourced_prerequisites():
    chain = normalize_chain(CHAIN, 'Classic Forever beta')
    report = {'completed_ids': [101], 'completion_coverage': 'available',
              'plan': [{'id': 102, 'action': 'turn in'}], 'warnings': ['Snapshot is old.']}
    result = annotate_chain(chain, report)
    assert [r['observed'] for r in result['nodes']] == ['Completed in saved snapshot', 'Objectives done; turn-in unobserved', 'Not observed; completion unknown']
    assert result['nodes'][2]['requires'] == [102, 104]
    text = chain_text(result)
    assert 'Snapshot is old.' in text and '104' in text and 'uncertain' in text.lower()
    assert 'https://example.com/quest' in text
    assert 'Next quests (reported): 103' in text


def test_cycles_missing_sources_and_ambiguous_relations_are_explicit():
    raw = deepcopy(CHAIN); raw['nodes'][0]['requires'] = [103]
    result = normalize_chain(raw, 'Classic Forever beta')
    assert 'cycle' in ' '.join(result['caveats']).lower()
    assert 'missing' in ' '.join(result['caveats']).lower()
    assert result['nodes'][2]['evidence_state'] == 'Unverified claim'


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(edition='Retail'),
    lambda r: r.update(nodes=r['nodes'] * 12),
    lambda r: r['nodes'][0].update(id=True),
    lambda r: r['nodes'][0].update(requires=[[]]),
    lambda r: r['nodes'][0].update(relation='invented'),
    lambda r: r['nodes'][0].update(relation=[]),
], ids=['edition', 'oversize', 'bad-id', 'nested', 'relation', 'nested-relation'])
def test_unsupported_chain_results_fail_closed(mutate):
    raw = deepcopy(CHAIN); mutate(raw)
    with pytest.raises(ChatError):
        normalize_chain(raw, 'Classic Forever beta')


def test_invalid_urls_are_omitted_and_absence_is_not_completion():
    raw = deepcopy(CHAIN); raw['nodes'][0]['sources'] = ['file:///private', 'https://user:pass@example.com']
    result = annotate_chain(normalize_chain(raw, raw['edition']), {'completed_ids': None, 'plan': []})
    assert not result['nodes'][0]['sources']
    assert all(r['observed'] == 'Not observed; completion unknown' for r in result['nodes'])
