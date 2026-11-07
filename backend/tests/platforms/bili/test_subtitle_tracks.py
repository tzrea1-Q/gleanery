from gleanery.platforms.bili.driver import original_tracks


def test_drops_machine_translated_tracks() -> None:
    tracks = [
        {"lan": "ai-zh", "type": 1, "ai_type": 0, "subtitle_url": "//a"},
        {"lan": "ai-en", "type": 1, "ai_type": 1, "subtitle_url": "//b"},
        {"lan": "zh-CN", "type": 0, "subtitle_url": "//c"},
        "坏数据",
    ]
    assert [track["lan"] for track in original_tracks(tracks)] == ["ai-zh", "zh-CN"]
    assert original_tracks(None) == []
