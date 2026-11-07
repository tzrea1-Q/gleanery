from gleanery.collect.estimate import content_seconds, estimate_task_seconds, remaining_seconds
from gleanery.collect.plan import PlatformSection
from gleanery.collect.types import DEFAULT_RATE_LIMITS
from gleanery.platforms.types import Depth


def test_estimates_by_platform() -> None:
    depth = Depth(comments=20, sub_comments=True, sub_comments_per_root=10)
    bili = PlatformSection(platform="bili", keywords=["a"], quantity=21, depth=depth)
    xhs = PlatformSection(platform="xhs", keywords=["a"], quantity=21, depth=depth)
    limits = DEFAULT_RATE_LIMITS["bili"]
    assert content_seconds(bili, limits) == 33
    assert content_seconds(xhs, limits) == 57.5
    assert estimate_task_seconds(bili, limits) == 704
    assert estimate_task_seconds(xhs, limits) == 1218
    assert remaining_seconds(xhs, limits, 2, False) == 115
