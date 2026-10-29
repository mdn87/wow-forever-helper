"""Synthetic tooltip facts; no captured game data or item database."""

from copy import deepcopy
import pytest

from wow_helper.chat import ChatError
from wow_helper.gear_compare import compare, normalize


def sample():
    def item(name, x, equipped, stats):
        return dict(name=name, variant='Example variant', slot='finger', item_level=100,
                    equipped_label=equipped, bounds=[x, 0, 100, 200], complete=True,
                    stats=[dict(name=n, value=v, unit=u) for n, v, u in stats], effects=[])
    return dict(edition='Retail', warnings=[],
                candidate=item('Example candidate', 0, False, [('Stamina', 50, 'points'), ('Haste', 1.5, 'percent')]),
                equipped=[item('Example equipped', 120, True, [('Stamina', 80, 'points'), ('Haste', 1, 'percent')])])


def test_deltas_are_calculated_from_observed_fields():
    result = compare(normalize(sample(), 'Retail', (400, 300)))
    assert result[0]['deltas'] == [{'name': 'stamina', 'unit': 'points', 'delta': -30},
                                  {'name': 'haste', 'unit': 'percent', 'delta': 0.5}]


def test_missing_stat_and_different_unit_are_unknown_not_zero():
    data = sample()
    data['equipped'][0]['stats'][1]['unit'] = 'points'
    result = compare(normalize(data, 'Retail', (400, 300)))[0]
    assert len(result['deltas']) == 1
    assert 'haste' in ' '.join(result['unknowns'])


def test_two_equipped_rings_remain_separate_comparisons():
    data = sample()
    other = deepcopy(data['equipped'][0])
    other.update(name='Example second ring', bounds=[240, 0, 100, 200])
    other['stats'][0]['value'] = 20
    data['equipped'].append(other)
    results = compare(normalize(data, 'Retail', (400, 300)))
    assert [r['deltas'][0]['delta'] for r in results] == [-30, 30]
    assert [r['equipped_index'] for r in results] == [0, 1]


@pytest.mark.parametrize('damage', [
    lambda d: d.update(edition='Classic'),
    lambda d: d.update(candidate=None),
    lambda d: d.update(equipped=[]),
    lambda d: d['equipped'][0].update(equipped_label=False),
    lambda d: d['equipped'][0].update(bounds=[0, 0, 100, 200]),
    lambda d: d['candidate'].update(bounds=[0, 0, 999, 200]),
    lambda d: d['candidate']['stats'][0].update(value=float('nan')),
    lambda d: d['candidate']['stats'][0].update(value=True),
    lambda d: d['candidate']['stats'].append(d['candidate']['stats'][0]),
    lambda d: d['equipped'][0].update(slot='head'),
])
def test_ambiguous_or_invalid_extraction_refuses_comparison(damage):
    data = sample(); damage(data)
    with pytest.raises(ChatError):
        normalize(data, 'Retail', (400, 300))


def test_unknown_values_and_effects_are_preserved_without_ranking():
    data = sample()
    data['candidate']['stats'][0]['value'] = None
    data['candidate']['effects'] = ['Example effect, numerical strength unreadable']
    result = compare(normalize(data, 'Retail', (400, 300)))[0]
    assert all(row['name'] != 'stamina' for row in result['deltas'])
    assert 'stamina' in ' '.join(result['unknowns'])
    assert 'upgrade_percent' not in result
