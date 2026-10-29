"""Synthetic image regions; never capture the live desktop."""

import pytest
from PIL import Image
from wow_helper.chat import ChatError
from wow_helper.screen_capture import crop_region


def test_only_reviewed_region_pixels_are_retained():
    source = Image.new('RGB', (100, 80), 'red')
    source.paste('blue', (20, 10, 60, 50))
    image = crop_region(source, [20, 10, 40, 40], [100, 80])
    assert image.size == (40, 40)
    assert image.getextrema() == ((0, 0), (0, 0), (255, 255))


@pytest.mark.parametrize('region,size', [([-1, 0, 10, 10], [100, 80]),
                                       ([90, 0, 20, 20], [100, 80]),
                                       ([0, 0, 10, 10], [101, 80]),
                                       ([0, 0, 10, 10], None),
                                       ([True, 0, 10, 10], [100, 80])])
def test_invalid_or_changed_geometry_requires_new_preview(region, size):
    with pytest.raises(ChatError, match='preview'):
        crop_region(Image.new('RGB', (100, 80)), region, size)
