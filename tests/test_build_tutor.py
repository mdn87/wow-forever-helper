"""Synthetic profile imports; no simulator or game data is used."""

import pytest

from wow_helper.chat import ChatError
from wow_helper.build_tutor import parse_profile, prepare_build


PROFILE = '# Synthetic profile\npriest="Testchar"\nspec=shadow\nlevel=80\ntalents=ABC123/==\nhead=example,id=123,bonus_id=4/5\n'


def test_profile_is_static_data_and_omits_identity_and_unsupported_values():
    result = parse_profile(PROFILE + 'server=ExampleRealm\ninput=do-not-read\nactions=/do-not-run\n', 'Retail')
    assert result['class'] == 'priest'
    assert result['items']['head']['id'] == '123'
    assert set(result['unsupported']) == {'input', 'actions'}
    assert all(value not in str(result) for value in ('Testchar', 'ExampleRealm', 'do-not-read', 'do-not-run'))


@pytest.mark.parametrize('body,edition', [
    (PROFILE, 'Classic Forever beta'), (PROFILE + 'mage=Testchar', 'Retail'),
    (PROFILE + 'spec=holy', 'Retail'), (PROFILE + 'edition=Classic', 'Retail'),
    ('x' * 64001, 'Retail'), ('priest=Testchar\nnot a directive', 'Retail'),
    ('priest=Testchar\nhead=example,id=oops', 'Retail'),
], ids=['edition', 'actors', 'duplicate', 'mismatch', 'oversize', 'malformed', 'item'])
def test_invalid_profiles_are_refused_without_execution(body, edition):
    with pytest.raises(ChatError):
        parse_profile(body, edition)


def test_missing_fields_and_unverified_report_are_visible():
    data = dict(edition='Retail', format='SimulationCraft profile', profile='priest=Testchar',
                role='Damage', preferences='Simple rotation', question='Which talent should I compare?',
                report='Synthetic result: 123 DPS', engine='Unknown', report_edition='Retail')
    packet = prepare_build(data)
    evidence = packet['reports']['build']['data']
    assert 'talents' in ' '.join(evidence['gaps']) and 'items' in ' '.join(evidence['gaps'])
    assert 'unverified' in evidence['report']['status'].lower()
    assert 'numerical gains' in packet['instructions']
    data['report_edition'] = 'Classic'
    with pytest.raises(ChatError, match='edition'):
        prepare_build(data)


def test_manual_build_notes_support_other_editions_without_simulation_claims():
    packet = prepare_build(dict(edition='Classic Forever beta', format='Build notes', profile='Prefer healing.',
                               role='Healer', preferences='', question='Explain this choice.', report='', engine='',
                               report_edition='Classic Forever beta'))
    assert packet['reports']['build']['data']['profile']['notes'] == 'Prefer healing.'
    assert packet['skills'] == [] and packet['context_files'] == []
