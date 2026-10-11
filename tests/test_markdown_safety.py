from settlement.markdown_safety import neutralize_images, safe_lines


def test_image_syntax_is_neutralized():
    assert neutralize_images("![x](https://evil.example/?d=1)") == r"\![x](https://evil.example/?d=1)"


def test_links_and_plain_text_unchanged():
    text = "| 이도윤 | 60% | [계약](https://example.com) 확인!"
    assert neutralize_images(text) == text


def test_image_split_across_chunks_is_caught():
    chunks = ["표입니다\n!", "[x](https://evil.example)", "\n끝"]
    assert "".join(safe_lines(chunks)) == "표입니다\n\\![x](https://evil.example)\n끝"
