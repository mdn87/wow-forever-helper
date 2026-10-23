"""Hand-written synthetic routes; no addon database or gameplay capture."""

import pytest

from wow_helper.chat import ChatError
from wow_helper.route_notebook import prepare_route


def form(**changes):
    return dict(edition='Classic Forever beta', route_edition='Classic Forever beta',
                dungeon='Example dungeon', role='Healer', phase='Preparation',
                question='Explain the first two pulls.', route='1. Example entrance\n2. Example hallway',
                observations='', image='', **changes)


def test_route_keeps_claims_separate_from_observations(tmp_path):
    values = form()
    values.update(phase='Review run', observations='We stopped before the second pull.')
    packet = prepare_route(values, tmp_path)
    data = packet['reports']['route']['data']
    assert data['observations'] == values['observations']
    assert data['numbered_pulls'] == 2
    assert 'unverified' in ' '.join(data['gaps'])
    assert 'sources' in packet['instructions']


@pytest.mark.parametrize('changes', [
    {'route': '!MDT!compressed-data'}, {'route': 'x' * 40001},
    {'route': '{"version":999}'}, {'route_edition': 'Retail'},
    {'route': 'edition: Retail\n1. Example entrance'},
    {'route': '', 'image': ''}, {'phase': 'Review run', 'observations': ''},
], ids=['mdt', 'oversize', 'serialized', 'edition', 'inline-edition', 'empty', 'review-empty'])
def test_unsupported_routes_are_explicit(tmp_path, changes):
    values = form(); values.update(changes)
    with pytest.raises(ChatError):
        prepare_route(values, tmp_path)


def test_missing_pulls_and_image_are_never_guessed(tmp_path):
    values = form(); values['route'] = 'Discuss this example entrance.'
    assert 'No numbered pulls' in ' '.join(prepare_route(values, tmp_path)['reports']['route']['data']['gaps'])
    values['image'] = '00000000-0000-0000-0000-000000000000.png'
    with pytest.raises(ChatError, match='unavailable'):
        prepare_route(values, tmp_path)
