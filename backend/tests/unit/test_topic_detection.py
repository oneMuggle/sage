from backend.chat.topic_detection import detect_topic_shift


def test_quick_signal_chinese():
    is_new, reason = detect_topic_shift("换个话题，我想问下...", [])
    assert is_new is True
    assert reason == "quick_signal"


def test_quick_signal_english():
    is_new, reason = detect_topic_shift("By the way, completely different question.", [])
    assert is_new is True
    assert reason == "quick_signal"


def test_no_signal_no_embed_fn_returns_false():
    is_new, reason = detect_topic_shift("继续解释上一段", ["hello"])
    assert is_new is False
    assert reason == "no_signal"


def test_embed_low_similarity_triggers():
    def fake_embed(text: str):
        return [0.0] * 384 if "weather" in text.lower() else [1.0] + [0.0] * 383
    is_new, reason = detect_topic_shift(
        "What's the weather today?",
        ["Sure, here's the bug fix..."],
        embed_fn=fake_embed,
    )
    assert is_new is True
    assert reason == "embed_similarity"


def test_embed_high_similarity_no_trigger():
    def fake_embed(text: str):
        return [1.0] + [0.0] * 383
    is_new, reason = detect_topic_shift(
        "Tell me more about that.",
        ["Here's a detailed explanation of X."],
        embed_fn=fake_embed,
    )
    assert is_new is False
    assert reason == "embed_similarity"
