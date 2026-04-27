from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, Tag

from qa_bot.domain.models import FormInfo, HeadingInfo, ImageInfo, LinkInfo, PreprocessedPage

_REMOVE_TAGS = {"script", "style", "nav", "footer", "header", "iframe", "noscript"}

_FORM_INPUT_TAGS = {"input", "select", "textarea"}

_ws_re = re.compile(r" {2,}")


def preprocess(html: str) -> PreprocessedPage:
    if not html or not html.strip():
        return PreprocessedPage(
            title=None,
            text_content="",
            images=[],
            links=[],
            forms=[],
            meta_tags={},
            headings=[],
        )

    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    meta_tags = _extract_meta_tags(soup)

    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()

    head = soup.find("head")
    if head:
        head.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    text_content = _extract_text(soup)
    images = _extract_images(soup)
    links = _extract_links(soup)
    forms = _extract_forms(soup)
    headings = _extract_headings(soup)

    return PreprocessedPage(
        title=title,
        text_content=text_content,
        images=images,
        links=links,
        forms=forms,
        meta_tags=meta_tags,
        headings=headings,
    )


def _extract_text(soup: BeautifulSoup) -> str:
    raw = soup.get_text(separator=" ")
    lines = (_ws_re.sub(" ", line.strip()) for line in raw.splitlines())
    return "\n".join(line for line in lines if line)


def _extract_images(soup: BeautifulSoup) -> list[ImageInfo]:
    images = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        alt = img.get("alt") or None
        images.append(ImageInfo(src=str(src), alt=alt))
    return images


def _extract_links(soup: BeautifulSoup) -> list[LinkInfo]:
    links = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        text = a.get_text(strip=True)
        links.append(LinkInfo(href=str(href), text=text))
    return links


def _extract_forms(soup: BeautifulSoup) -> list[FormInfo]:
    forms = []
    for form in soup.find_all("form"):
        inputs_count = 0
        has_labels = False

        for tag in form.find_all(_FORM_INPUT_TAGS):
            inputs_count += 1

            input_id = tag.get("id")
            if input_id:
                label = form.find("label", attrs={"for": input_id})
                if label:
                    has_labels = True
                    continue

            parent = tag.parent
            if isinstance(parent, Tag) and parent.name == "label":
                has_labels = True

        forms.append(FormInfo(inputs_count=inputs_count, has_labels=has_labels))
    return forms


def _extract_meta_tags(soup: BeautifulSoup) -> dict[str, str]:
    meta_tags: dict[str, str] = {}
    for meta in soup.find_all("meta"):
        key = meta.get("name") or meta.get("property")
        content = meta.get("content")
        if key and content:
            meta_tags[str(key)] = str(content)
    return meta_tags


def _extract_headings(soup: BeautifulSoup) -> list[HeadingInfo]:
    headings = []
    for level in range(1, 7):
        for tag in soup.find_all(f"h{level}"):
            text = tag.get_text(strip=True)
            if text:
                headings.append(HeadingInfo(level=level, text=text))
    return headings
