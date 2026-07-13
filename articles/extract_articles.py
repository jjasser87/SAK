#!/usr/bin/env python3
"""Extract the readable portion of web articles and save it as Markdown or PDF."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify
from PIL import Image as PillowImage
from readability import Document
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import (
    A0,
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    LEGAL,
    LEDGER,
    LETTER,
    TABLOID,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


USER_AGENT = "SAK Article Extractor/1.0"
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(
    r"(!?)\[[^\]]*\]\((https?://[^\s)]+)(?:\s+[\"'][^)]*)?\)",
    re.IGNORECASE,
)
MAX_HTML_BYTES = 15 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
PAGE_SIZES = {
    "LETTER": LETTER,
    "LEGAL": LEGAL,
    "TABLOID": TABLOID,
    "LEDGER": LEDGER,
    "EXECUTIVE": (7.25 * inch, 10.5 * inch),
    "A0": A0,
    "A1": A1,
    "A2": A2,
    "A3": A3,
    "A4": A4,
    "A5": A5,
    "A6": A6,
}


@dataclass(frozen=True)
class Article:
    title: str
    source_url: str
    content_html: str
    byline: str | None = None
    published: str | None = None
    site_name: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract article text and images from URLs into Markdown or PDF."
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="One or more http(s) URLs, or .txt/.md files containing URLs.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "pdf", "both"),
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Destination directory. Defaults to output/articles for Markdown and output/pdf for PDF.",
    )
    parser.add_argument(
        "--combine",
        nargs="?",
        const="articles",
        metavar="NAME",
        help="Combine all articles into one artifact, optionally using NAME as its filename.",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Remove images instead of downloading and including them.",
    )
    parser.add_argument(
        "--page-size",
        type=str.upper,
        choices=PAGE_SIZES,
        default="LETTER",
        help="PDF print size. Defaults to LETTER.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="Per-request timeout in seconds. Defaults to 30.",
    )
    parser.add_argument(
        "--user-agent",
        default=USER_AGENT,
        help="HTTP User-Agent header used to fetch pages and images.",
    )
    return parser.parse_args(argv)


def is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def extract_urls_from_text(text: str) -> list[str]:
    """Find Markdown-link and bare HTTP URLs while preserving their order."""
    candidates: list[tuple[int, str]] = []
    markdown_spans: list[tuple[int, int]] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        if not match.group(1):
            candidates.append((match.start(2), match.group(2)))
        markdown_spans.append(match.span())

    for match in URL_RE.finditer(text):
        if any(start <= match.start() < end for start, end in markdown_spans):
            continue
        url = match.group(0).rstrip(".,;:!?\"'")
        candidates.append((match.start(), url))

    seen: set[str] = set()
    urls: list[str] = []
    for _, url in sorted(candidates):
        if is_http_url(url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def collect_urls(sources: Iterable[str]) -> list[str]:
    urls: list[str] = []
    for source in sources:
        if is_http_url(source):
            urls.append(source)
            continue

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Source is neither a valid URL nor an existing file: {source}")
        if path.suffix.lower() not in {".txt", ".md", ".markdown"}:
            raise ValueError(f"URL list must be a .txt, .md, or .markdown file: {path}")
        file_urls = extract_urls_from_text(path.read_text(encoding="utf-8"))
        if not file_urls:
            raise ValueError(f"No HTTP URLs found in: {path}")
        urls.extend(file_urls)

    return list(dict.fromkeys(urls))


def meta_content(soup: BeautifulSoup, *selectors: tuple[str, str]) -> str | None:
    for attribute, value in selectors:
        tag = soup.find("meta", attrs={attribute: value})
        if tag and tag.get("content"):
            content = str(tag["content"]).strip()
            if content:
                return content
    return None


def normalize_image_source(tag: Tag, base_url: str) -> str | None:
    source = None
    for attribute in ("data-src", "data-lazy-src", "data-original", "src"):
        value = tag.get(attribute)
        if value and not str(value).startswith("data:"):
            source = str(value).strip()
            break

    srcset = tag.get("data-srcset") or tag.get("srcset")
    if srcset:
        entries = [part.strip().split()[0] for part in str(srcset).split(",") if part.strip()]
        if entries:
            source = entries[-1]

    if not source:
        return None
    absolute = urljoin(base_url, source)
    return absolute if is_http_url(absolute) else None


def extract_article(page_html: str, source_url: str) -> Article:
    original = BeautifulSoup(page_html, "html.parser")
    document = Document(page_html, url=source_url)
    readable_html = document.summary(html_partial=True)
    content = BeautifulSoup(readable_html, "html.parser")

    for unwanted in content.select("script, style, nav, form, button, noscript, iframe, canvas"):
        unwanted.decompose()

    for link in content.find_all("a", href=True):
        link["href"] = urljoin(source_url, str(link["href"]))

    for image in list(content.find_all("img")):
        width = str(image.get("width", "")).strip()
        height = str(image.get("height", "")).strip()
        if width.isdigit() and height.isdigit() and int(width) <= 2 and int(height) <= 2:
            image.decompose()
            continue
        source = normalize_image_source(image, source_url)
        if not source:
            image.decompose()
            continue
        image["src"] = source
        for attribute in ("srcset", "data-srcset", "data-src", "data-lazy-src", "data-original"):
            image.attrs.pop(attribute, None)

    title = (
        meta_content(original, ("property", "og:title"), ("name", "twitter:title"))
        or document.short_title()
        or (original.title.get_text(" ", strip=True) if original.title else None)
        or urlparse(source_url).netloc
    )
    normalized_title = re.sub(r"\W+", " ", html.unescape(title)).strip().casefold()
    first_heading = content.find("h1")
    if first_heading:
        normalized_heading = re.sub(
            r"\W+", " ", first_heading.get_text(" ", strip=True)
        ).strip().casefold()
        if normalized_heading == normalized_title:
            first_heading.decompose()
    byline = meta_content(
        original,
        ("name", "author"),
        ("property", "article:author"),
        ("name", "byl"),
    )
    published = meta_content(
        original,
        ("property", "article:published_time"),
        ("name", "date"),
        ("name", "pubdate"),
        ("itemprop", "datePublished"),
    )
    site_name = meta_content(original, ("property", "og:site_name"))

    return Article(
        title=html.unescape(title).strip(),
        source_url=source_url,
        content_html=str(content),
        byline=html.unescape(byline).strip() if byline else None,
        published=published,
        site_name=html.unescape(site_name).strip() if site_name else None,
    )


class Downloader:
    def __init__(self, timeout: float, user_agent: str) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "en-US,en;q=0.8",
            }
        )

    def fetch_html(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type and "xhtml" not in content_type:
            raise ValueError(f"URL did not return HTML ({content_type.split(';')[0]}): {url}")
        if len(response.content) > MAX_HTML_BYTES:
            raise ValueError(f"HTML response exceeds {MAX_HTML_BYTES // (1024 * 1024)} MB: {url}")
        response.encoding = response.encoding or response.apparent_encoding
        return response.text

    def fetch_image(self, url: str) -> tuple[bytes, str]:
        response = self.session.get(url, timeout=self.timeout, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
            chunks.append(chunk)
        return b"".join(chunks), content_type


def slugify(value: str, default: str = "article") -> str:
    value = html.unescape(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:90].rstrip("-") or default


def save_image(data: bytes, destination_stem: Path) -> Path:
    """Validate and normalize an image to JPEG or PNG for portable output."""
    with PillowImage.open(io.BytesIO(data)) as image:
        image.load()
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        if has_alpha:
            output = destination_stem.with_suffix(".png")
            image.convert("RGBA").save(output, "PNG", optimize=True)
        else:
            output = destination_stem.with_suffix(".jpg")
            image.convert("RGB").save(output, "JPEG", quality=88, optimize=True)
    return output


def localize_images(
    content_html: str,
    assets_dir: Path,
    downloader: Downloader,
    relative_to: Path | None = None,
) -> tuple[str, dict[str, Path], list[str]]:
    soup = BeautifulSoup(content_html, "html.parser")
    assets_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    warnings: list[str] = []

    for index, image in enumerate(soup.find_all("img"), start=1):
        source = str(image.get("src", ""))
        if not is_http_url(source):
            image.decompose()
            continue
        if source not in paths:
            try:
                data, _ = downloader.fetch_image(source)
                digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:10]
                paths[source] = save_image(data, assets_dir / f"image-{index:03d}-{digest}")
            except Exception as exc:
                warnings.append(f"Could not download image {source}: {exc}")
                continue

        if relative_to is not None:
            image["src"] = paths[source].relative_to(relative_to).as_posix()

    return str(soup), paths, warnings


def article_metadata_markdown(article: Article) -> str:
    details = [item for item in (article.byline, article.published, article.site_name) if item]
    lines = [f"# {article.title}", ""]
    if details:
        lines.extend([f"*{' · '.join(details)}*", ""])
    lines.extend([f"Source: [{article.source_url}]({article.source_url})", ""])
    return "\n".join(lines)


def render_markdown(
    articles: list[Article],
    output_path: Path,
    downloader: Downloader,
    include_images: bool,
) -> list[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = output_path.parent / f"{output_path.stem}_assets"
    sections: list[str] = []
    warnings: list[str] = []

    for article in articles:
        content_html = article.content_html
        if include_images:
            content_html, _, image_warnings = localize_images(
                content_html, assets_dir, downloader, relative_to=output_path.parent
            )
            warnings.extend(image_warnings)
        else:
            soup = BeautifulSoup(content_html, "html.parser")
            for image in soup.find_all("img"):
                image.decompose()
            content_html = str(soup)

        body = markdownify(
            content_html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        ).strip()
        sections.append(f"{article_metadata_markdown(article)}\n{body}".rstrip())

    output_path.write_text("\n\n---\n\n".join(sections) + "\n", encoding="utf-8")
    if include_images and not any(assets_dir.iterdir()):
        assets_dir.rmdir()
    return warnings


def pdf_styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ArticleTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=colors.HexColor("#172033"),
            spaceAfter=12,
        ),
        "meta": ParagraphStyle(
            "ArticleMeta",
            parent=sample["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#596579"),
            spaceAfter=5,
        ),
        "source": ParagraphStyle(
            "ArticleSource",
            parent=sample["Normal"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#3267a8"),
            spaceAfter=16,
        ),
        "body": ParagraphStyle(
            "ArticleBody",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15.5,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=9,
        ),
        "blockquote": ParagraphStyle(
            "ArticleQuote",
            parent=sample["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            leading=15,
            leftIndent=18,
            rightIndent=12,
            borderColor=colors.HexColor("#9ba8ba"),
            borderWidth=1.5,
            borderPadding=7,
            spaceAfter=10,
        ),
        "code": ParagraphStyle(
            "ArticleCode",
            parent=sample["Code"],
            fontName="Courier",
            fontSize=8,
            leading=11,
            leftIndent=10,
            rightIndent=10,
            backColor=colors.HexColor("#f3f4f6"),
            borderPadding=7,
            spaceAfter=10,
        ),
        "caption": ParagraphStyle(
            "ArticleCaption",
            parent=sample["Normal"],
            alignment=TA_CENTER,
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#687386"),
            spaceAfter=12,
        ),
        **{
            f"h{level}": ParagraphStyle(
                f"ArticleH{level}",
                parent=sample[f"Heading{min(level, 3)}"],
                fontName="Helvetica-Bold",
                fontSize={1: 18, 2: 15, 3: 13, 4: 11.5, 5: 10.5, 6: 10}[level],
                leading={1: 22, 2: 19, 3: 17, 4: 15, 5: 14, 6: 14}[level],
                textColor=colors.HexColor("#172033"),
                spaceBefore=10,
                spaceAfter=6,
            )
            for level in range(1, 7)
        },
    }


def inline_markup(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return html.escape(str(node))
    if not isinstance(node, Tag) or node.name == "img":
        return ""

    inner = "".join(inline_markup(child) for child in node.children)
    if node.name in {"strong", "b"}:
        return f"<b>{inner}</b>"
    if node.name in {"em", "i"}:
        return f"<i>{inner}</i>"
    if node.name == "u":
        return f"<u>{inner}</u>"
    if node.name == "br":
        return "<br/>"
    if node.name == "code":
        return f'<font name="Courier">{inner}</font>'
    if node.name in {"sup", "sub"}:
        return f"<{node.name}>{inner}</{node.name}>"
    if node.name == "a" and node.get("href"):
        href = html.escape(str(node["href"]), quote=True)
        return f'<a href="{href}" color="#3267a8">{inner}</a>'
    return inner


def image_flowable(path: Path, max_width: float, max_height: float = 6.6 * inch) -> Image:
    with PillowImage.open(path) as source:
        width, height = source.size
    scale = min(max_width / width, max_height / height, 1.0)
    return Image(str(path), width=width * scale, height=height * scale, hAlign="CENTER")


def table_flowable(
    tag: Tag, styles: dict[str, ParagraphStyle], content_width: float
) -> Table | None:
    rows: list[list[Paragraph]] = []
    for row in tag.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if cells:
            rows.append([Paragraph(inline_markup(cell).strip() or " ", styles["body"]) for cell in cells])
    if not rows:
        return None
    column_count = max(len(row) for row in rows)
    for row in rows:
        row.extend([Paragraph(" ", styles["body"])] * (column_count - len(row)))
    table = Table(rows, colWidths=[content_width / column_count] * column_count, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef5")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aab4c3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def html_to_flowables(
    content_html: str,
    image_paths: dict[str, Path],
    styles: dict[str, ParagraphStyle],
    content_width: float,
) -> list[object]:
    soup = BeautifulSoup(content_html, "html.parser")
    story: list[object] = []

    def add_image(tag: Tag) -> None:
        source = str(tag.get("src", ""))
        path = image_paths.get(source)
        if path:
            story.extend(
                [Spacer(1, 5), image_flowable(path, content_width), Spacer(1, 7)]
            )
            alt = str(tag.get("alt", "")).strip()
            if alt:
                story.append(Paragraph(html.escape(alt), styles["caption"]))

    def visit(parent: Tag | BeautifulSoup) -> None:
        for child in parent.children:
            if isinstance(child, NavigableString):
                text = str(child).strip()
                if text:
                    story.append(Paragraph(html.escape(text), styles["body"]))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name == "img":
                add_image(child)
            elif name in {f"h{level}" for level in range(1, 7)}:
                story.append(Paragraph(inline_markup(child).strip(), styles[name]))
            elif name == "p":
                markup = inline_markup(child).strip()
                if markup:
                    story.append(Paragraph(markup, styles["body"]))
                for image in child.find_all("img"):
                    add_image(image)
            elif name in {"ul", "ol"}:
                items = []
                for item in child.find_all("li", recursive=False):
                    markup = inline_markup(item).strip()
                    if markup:
                        items.append(ListItem(Paragraph(markup, styles["body"])))
                if items:
                    story.append(
                        ListFlowable(
                            items,
                            bulletType="1" if name == "ol" else "bullet",
                            leftIndent=22,
                            bulletFontName="Helvetica",
                            bulletFontSize=9,
                            spaceAfter=8,
                        )
                    )
            elif name == "pre":
                text = html.escape(child.get_text("\n", strip=False)).replace("\n", "<br/>")
                if text.strip():
                    story.append(Paragraph(text, styles["code"]))
            elif name == "blockquote":
                markup = inline_markup(child).strip()
                if markup:
                    story.append(Paragraph(markup, styles["blockquote"]))
            elif name == "figure":
                image = child.find("img")
                if image:
                    add_image(image)
                caption = child.find("figcaption")
                if caption:
                    story.append(Paragraph(inline_markup(caption), styles["caption"]))
            elif name == "table":
                table = table_flowable(child, styles, content_width)
                if table:
                    story.extend([table, Spacer(1, 10)])
            elif name == "hr":
                story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#aab4c3"), spaceBefore=7, spaceAfter=10))
            elif name not in {"figcaption", "li", "thead", "tbody", "tfoot", "tr", "td", "th"}:
                visit(child)

    visit(soup)
    return story


def page_footer(canvas, document) -> None:
    page_width, _ = document.pagesize
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d4dae3"))
    canvas.setLineWidth(0.4)
    canvas.line(
        document.leftMargin,
        0.53 * inch,
        page_width - document.rightMargin,
        0.53 * inch,
    )
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#687386"))
    canvas.drawRightString(
        page_width - document.rightMargin,
        0.34 * inch,
        f"Page {document.page}",
    )
    canvas.restoreState()


def render_pdf(
    articles: list[Article],
    output_path: Path,
    downloader: Downloader,
    include_images: bool,
    temp_root: Path,
    page_size: tuple[float, float] = LETTER,
) -> list[str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    styles = pdf_styles()
    warnings: list[str] = []
    left_margin = 0.72 * inch
    right_margin = 0.72 * inch
    content_width = page_size[0] - left_margin - right_margin

    with tempfile.TemporaryDirectory(prefix=f"{output_path.stem}-", dir=temp_root) as temp_dir:
        story: list[object] = []
        for article_index, article in enumerate(articles):
            if article_index:
                story.append(PageBreak())
            story.append(Paragraph(html.escape(article.title), styles["title"]))
            details = [item for item in (article.byline, article.published, article.site_name) if item]
            if details:
                story.append(Paragraph(html.escape(" · ".join(details)), styles["meta"]))
            source = html.escape(article.source_url, quote=True)
            story.append(Paragraph(f'Source: <a href="{source}">{source}</a>', styles["source"]))

            image_paths: dict[str, Path] = {}
            content_html = article.content_html
            if include_images:
                content_html, image_paths, image_warnings = localize_images(
                    content_html,
                    Path(temp_dir) / f"article-{article_index + 1}",
                    downloader,
                )
                warnings.extend(image_warnings)
            else:
                soup = BeautifulSoup(content_html, "html.parser")
                for image in soup.find_all("img"):
                    image.decompose()
                content_html = str(soup)
            story.extend(
                html_to_flowables(content_html, image_paths, styles, content_width)
            )

        document = SimpleDocTemplate(
            str(output_path),
            pagesize=page_size,
            rightMargin=right_margin,
            leftMargin=left_margin,
            topMargin=0.7 * inch,
            bottomMargin=0.72 * inch,
            title=articles[0].title if len(articles) == 1 else output_path.stem,
            author="Swiss Army Knife Article Extractor",
        )
        document.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    return warnings


def output_path_for(article: Article, output_dir: Path, suffix: str, used: set[str]) -> Path:
    stem = slugify(article.title)
    if stem in used:
        digest = hashlib.sha256(article.source_url.encode("utf-8")).hexdigest()[:8]
        stem = f"{stem}-{digest}"
    used.add(stem)
    return output_dir / f"{stem}{suffix}"


def run(args: argparse.Namespace) -> int:
    try:
        urls = collect_urls(args.sources)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    downloader = Downloader(args.timeout, args.user_agent)
    articles: list[Article] = []
    failures: list[str] = []
    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] Extracting {url}")
        try:
            articles.append(extract_article(downloader.fetch_html(url), url))
        except Exception as exc:
            failures.append(f"{url}: {exc}")

    if not articles:
        print("No articles were extracted successfully.", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    formats = ("markdown", "pdf") if args.format == "both" else (args.format,)
    all_warnings: list[str] = []
    temp_root = Path("tmp/pdfs")

    for output_format in formats:
        used_stems: set[str] = set()
        if args.output_dir:
            output_dir = args.output_dir
        else:
            output_dir = Path("output/pdf" if output_format == "pdf" else "output/articles")
        suffix = ".pdf" if output_format == "pdf" else ".md"

        if args.combine:
            output_path = output_dir / f"{slugify(args.combine, 'articles')}{suffix}"
            batches = [(articles, output_path)]
        else:
            batches = [
                ([article], output_path_for(article, output_dir, suffix, used_stems))
                for article in articles
            ]

        for batch, output_path in batches:
            try:
                if output_format == "markdown":
                    warnings = render_markdown(
                        batch, output_path, downloader, include_images=not args.no_images
                    )
                else:
                    warnings = render_pdf(
                        batch,
                        output_path,
                        downloader,
                        include_images=not args.no_images,
                        temp_root=temp_root,
                        page_size=PAGE_SIZES[args.page_size],
                    )
                all_warnings.extend(warnings)
                print(f"Created: {output_path}")
            except Exception as exc:
                failures.append(f"Could not create {output_path}: {exc}")

    for warning in all_warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    for failure in failures:
        print(f"Error: {failure}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
