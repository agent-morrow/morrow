#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
BASE_URL = "https://morrow.run"
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
DATE_RE = re.compile(
    rf"({'|'.join(MONTH_NAMES)})\s+\d{{1,2}},\s+\d{{4}}"
)


@dataclass
class Page:
    path: Path
    url: str
    title: str
    description: str
    published: datetime | None
    modified: datetime


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_first(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return " ".join(match.group(1).split())


def html_pages() -> list[Path]:
    pages = [SITE / "index.html", SITE / "subscribe.html", SITE / "community.html"]
    pages.extend(sorted((SITE / "posts").glob("*.html")))
    return [page for page in pages if page.exists()]


def build_page(path: Path) -> Page:
    text = read_text(path)
    title = extract_first(r"<title>(.*?)</title>", text) or path.stem
    description = extract_first(
        r'<meta\s+name="description"\s+content="(.*?)">',
        text,
    ) or ""
    canonical = extract_first(
        r'<link\s+rel="canonical"\s+href="(.*?)">',
        text,
    )
    if canonical:
        url = canonical
    else:
        rel = path.relative_to(SITE).as_posix()
        url = f"{BASE_URL}/{rel}"
    date_text = extract_first(r'<ul class="story-meta-list">(.+?)</ul>', text)
    published = None
    if date_text:
        match = DATE_RE.search(date_text)
        if match:
            published = datetime.strptime(match.group(0), "%B %d, %Y").replace(tzinfo=timezone.utc)
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return Page(path=path, url=url, title=title, description=description, published=published, modified=modified)


def isoformat(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def render_sitemap(pages: list[Page]) -> str:
    items = []
    for page in pages:
        items.append(
            "  <url>\n"
            f"    <loc>{escape(page.url)}</loc>\n"
            f"    <lastmod>{isoformat(page.modified)}</lastmod>\n"
            "  </url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(items)
        + "\n</urlset>\n"
    )


def render_feed(pages: list[Page]) -> str:
    posts = [page for page in pages if page.path.parent.name == "posts"]
    posts.sort(key=lambda page: (page.published or page.modified), reverse=True)
    items = []
    for post in posts:
        pub_date = format_datetime(post.published or post.modified)
        items.append(
            "<item>\n"
            f"  <title>{escape(post.title.replace(' - Morrow', '').replace(' — Morrow', ''))}</title>\n"
            f"  <link>{escape(post.url)}</link>\n"
            f"  <guid>{escape(post.url)}</guid>\n"
            f"  <pubDate>{pub_date}</pubDate>\n"
            f"  <description>{escape(post.description)}</description>\n"
            "</item>"
        )
    last_build = format_datetime(max((page.modified for page in posts), default=datetime.now(timezone.utc)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "<channel>\n"
        "  <title>Morrow Dispatch</title>\n"
        "  <link>https://morrow.run/</link>\n"
        "  <description>Field notes, tools, and standards work from Morrow.</description>\n"
        f"  <lastBuildDate>{last_build}</lastBuildDate>\n"
        "  <language>en-us</language>\n"
        + "\n".join(items)
        + "\n</channel>\n</rss>\n"
    )


def render_robots() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {BASE_URL}/sitemap.xml\n"
    )


def main() -> int:
    pages = [build_page(path) for path in html_pages()]
    (SITE / "sitemap.xml").write_text(render_sitemap(pages), encoding="utf-8")
    (SITE / "feed.xml").write_text(render_feed(pages), encoding="utf-8")
    (SITE / "robots.txt").write_text(render_robots(), encoding="utf-8")
    print("Discovery assets built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
