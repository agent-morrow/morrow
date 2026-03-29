#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
POSTS = SITE / "posts"

REQUIRED_ARTICLE_CLASSES = [
    "story-shell",
    "story-home-link",
    "story-hero",
    "story-scorecard",
    "story-facts",
    "story-layout",
    "story-rail",
    "story-content",
]

ALLOWED_INLINE_STYLE = re.compile(r"^\s*--bar-fill:\s*\d{1,3}%\s*;?\s*$")
MORROW_GITHUB_PREFIX = "https://github.com/agent-morrow/morrow/blob/main/"


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.body_class = ""
        self.classes: list[str] = []
        self.class_set: set[str] = set()
        self.links: list[str] = []
        self.style_blocks = 0
        self.inline_styles: list[tuple[str, str, str]] = []
        self.images_missing_alt: list[str] = []
        self.h1_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        if tag == "body":
            self.body_class = attrs_dict.get("class", "")
        if tag == "style":
            self.style_blocks += 1
        if tag == "img" and not attrs_dict.get("alt", "").strip():
            self.images_missing_alt.append(tag)
        if tag == "h1":
            self.h1_count += 1

        class_attr = attrs_dict.get("class", "")
        if class_attr:
            classes = class_attr.split()
            self.classes.extend(classes)
            self.class_set.update(classes)

        href = attrs_dict.get("href")
        if href:
            self.links.append(href)

        style = attrs_dict.get("style", "")
        if style:
            self.inline_styles.append((tag, class_attr, style))


def check_link(source: Path, href: str, errors: list[str]) -> None:
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return

    if href.startswith(MORROW_GITHUB_PREFIX):
        rel = href.removeprefix(MORROW_GITHUB_PREFIX).split("#", 1)[0]
        if not (ROOT / rel).exists():
            errors.append(f"{source.name}: GitHub blob target missing locally: {rel}")
        return

    parsed = urlparse(href)
    if parsed.scheme in ("http", "https"):
        return

    if href.startswith("/"):
        target = SITE / href.lstrip("/")
    else:
        target = (source.parent / href).resolve()
    if not target.exists():
        errors.append(f"{source.name}: linked path missing: {href}")


def validate_article(path: Path) -> list[str]:
    parser = SiteParser()
    parser.feed(path.read_text(encoding="utf-8"))

    errors: list[str] = []
    if parser.body_class != "article-page":
        errors.append(f"{path.name}: body class must be article-page")
    if parser.h1_count != 1:
        errors.append(f"{path.name}: expected exactly one h1, found {parser.h1_count}")
    if parser.style_blocks:
        errors.append(f"{path.name}: inline <style> blocks are not allowed")

    for required in REQUIRED_ARTICLE_CLASSES:
        if required not in parser.classes:
            errors.append(f"{path.name}: missing required class {required}")

    if "story-section" not in parser.class_set:
        errors.append(f"{path.name}: article body must include at least one story-section wrapper")

    for tag, class_attr, style in parser.inline_styles:
        if "story-bar-fill" in class_attr and ALLOWED_INLINE_STYLE.match(style):
            continue
        errors.append(f"{path.name}: disallowed inline style on <{tag}>: {style}")

    for href in parser.links:
        check_link(path, href, errors)

    if parser.images_missing_alt:
        errors.append(f"{path.name}: image tags missing alt text")

    return errors


def validate_index(path: Path) -> list[str]:
    parser = SiteParser()
    parser.feed(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for href in parser.links:
        check_link(path, href, errors)
    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(validate_index(SITE / "index.html"))
    for article in sorted(POSTS.glob("*.html")):
        errors.extend(validate_article(article))

    if errors:
        print("Site validation failed:", file=sys.stderr)
        for err in errors:
            print(f" - {err}", file=sys.stderr)
        return 1

    print("Site validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
