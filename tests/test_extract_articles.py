import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from PIL import Image as PillowImage
from pypdf import PdfReader

from articles.extract_articles import (
    Article,
    PAGE_SIZES,
    PDFMargins,
    extract_article,
    extract_urls_from_text,
    normalize_image_source,
    parse_args,
    pdf_styles,
    render_markdown,
    render_pdf,
    resolve_pdf_margins,
    resolve_page_size,
)


SAMPLE_HTML = """
<!doctype html>
<html>
  <head>
    <title>Example Article - Example News</title>
    <meta property="og:title" content="Example Article">
    <meta property="og:site_name" content="Example News">
    <meta name="author" content="Ada Example">
    <meta property="article:published_time" content="2026-07-13">
  </head>
  <body>
    <nav>Unrelated navigation</nav>
    <article>
      <h1>Example Article</h1>
      <p>This is the opening paragraph with enough prose to identify the main article.</p>
      <img data-src="/images/hero.jpg" alt="A useful diagram">
      <h2>Details</h2>
      <p>The second paragraph contains <strong>important details</strong> and a
      <a href="/related">related link</a>.</p>
    </article>
    <footer>Unrelated footer</footer>
  </body>
</html>
"""
IGN_IMAGE_URL = (
    "https://oyster.ignimgs.com/mediawiki/apis.ign.com/octopath-traveler-2/9/9a/"
    "Octopath_Traveler_2_Prison_Underground_Passage_Map.png?"
    "width=814&dpr=2&format=jpg&auto=webp&quality=80"
)


class FakeDownloader:
    def __init__(self, image_bytes: bytes) -> None:
        self.image_bytes = image_bytes

    def fetch_image(self, url: str) -> tuple[bytes, str]:
        return self.image_bytes, "image/png"


class FailingDownloader:
    def fetch_image(self, url: str) -> tuple[bytes, str]:
        raise OSError("simulated image download failure")


def png_bytes() -> bytes:
    import io

    buffer = io.BytesIO()
    PillowImage.new("RGB", (320, 180), "#4b70a8").save(buffer, "PNG")
    return buffer.getvalue()


class ArticleExtractorTests(unittest.TestCase):
    def test_page_size_argument_is_case_insensitive(self) -> None:
        for value in ("legal", "gov_legal", "b5"):
            with self.subTest(page_size=value):
                args = parse_args(
                    ["https://example.com/story", "--page-size", value]
                )
                self.assertEqual(args.page_size, value.upper())

    def test_page_size_argument_accepts_custom_inches(self) -> None:
        for value in ("6.5x9", "6.5 in x 9 in", "6.5×9"):
            with self.subTest(page_size=value):
                args = parse_args(
                    ["https://example.com/story", "--page-size", value]
                )
                self.assertEqual(args.page_size, "6.5x9")

    def test_page_size_argument_rejects_invalid_custom_dimensions(self) -> None:
        for value in ("6.5", "wide-by-tall", "1x9", "6x201"):
            with self.subTest(page_size=value):
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    parse_args(["https://example.com/story", "--page-size", value])

    def test_scale_argument_accepts_scale_and_zoom_names(self) -> None:
        scale_args = parse_args(
            ["https://example.com/story", "--scale", "85"]
        )
        zoom_args = parse_args(
            ["https://example.com/story", "--zoom-scale", "125.5"]
        )

        self.assertEqual(scale_args.scale, 85)
        self.assertEqual(zoom_args.scale, 125.5)

    def test_margin_argument_accepts_uniform_and_per_side_values(self) -> None:
        args = parse_args(
            [
                "https://example.com/story",
                "--margin",
                "0.5",
                "--margin-top",
                "0.75",
                "--margin-left",
                "1",
            ]
        )
        margins = resolve_pdf_margins(args)

        self.assertEqual(margins.top, 0.75 * 72)
        self.assertEqual(margins.right, 0.5 * 72)
        self.assertEqual(margins.bottom, 0.5 * 72)
        self.assertEqual(margins.left, 1 * 72)

    def test_margin_defaults_preserve_existing_layout(self) -> None:
        args = parse_args(["https://example.com/story"])
        margins = resolve_pdf_margins(args)

        self.assertEqual(margins.top, 0.7 * 72)
        self.assertEqual(margins.right, 0.72 * 72)
        self.assertEqual(margins.bottom, 0.72 * 72)
        self.assertEqual(margins.left, 0.72 * 72)

    def test_margin_argument_rejects_invalid_or_incompatible_values(self) -> None:
        cases = (
            ("--margin", "not-a-number"),
            ("--margin", "-0.1"),
            ("--margin-left", "8"),
        )
        for option, value in cases:
            with self.subTest(option=option, value=value):
                with patch("sys.stderr"), self.assertRaises(SystemExit):
                    parse_args(
                        ["https://example.com/story", option, value]
                    )

    def test_pdf_styles_apply_scale(self) -> None:
        normal = pdf_styles()
        enlarged = pdf_styles(1.5)

        self.assertEqual(enlarged["body"].fontSize, normal["body"].fontSize * 1.5)
        self.assertEqual(enlarged["body"].leading, normal["body"].leading * 1.5)
        self.assertEqual(enlarged["h2"].spaceAfter, normal["h2"].spaceAfter * 1.5)

    def test_scale_changes_pdf_pagination(self) -> None:
        article = Article(
            title="Scale Test",
            source_url="https://example.com/story",
            content_html="".join(
                f"<h2>Section {index}</h2>"
                "<p>Scaling changes typography, spacing, and pagination in the "
                "generated document while preserving the physical page size.</p>"
                for index in range(30)
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page_counts = []
            for scale in (0.75, 1.5):
                output = root / f"article-{scale}.pdf"
                render_pdf(
                    [article],
                    output,
                    FakeDownloader(png_bytes()),
                    include_images=False,
                    temp_root=root / "tmp",
                    scale=scale,
                )
                page_counts.append(len(PdfReader(output).pages))

            self.assertLess(page_counts[0], page_counts[1])

    def test_remote_images_argument(self) -> None:
        args = parse_args(["https://example.com/story", "--remote-images"])
        self.assertTrue(args.remote_images)

    def test_extract_urls_from_markdown_and_plain_text(self) -> None:
        text = """
        - https://example.com/one
        - [Second](https://example.com/two)
        - ![Not an article](https://example.com/image.jpg)
        - duplicate: https://example.com/one
        """
        self.assertEqual(
            extract_urls_from_text(text),
            ["https://example.com/one", "https://example.com/two"],
        )

    def test_extract_article_keeps_content_and_normalizes_urls(self) -> None:
        article = extract_article(SAMPLE_HTML, "https://example.com/story")
        self.assertEqual(article.title, "Example Article")
        self.assertEqual(article.byline, "Ada Example")
        self.assertEqual(article.site_name, "Example News")
        self.assertIn("https://example.com/images/hero.jpg", article.content_html)
        self.assertIn("https://example.com/related", article.content_html)
        self.assertNotIn("Unrelated navigation", article.content_html)

    def test_normalize_image_source_preserves_commas_inside_srcset_urls(self) -> None:
        largest = (
            "https://media.example.com/photos/id/master/"
            "w_1600,c_limit/Album-Art.jpg"
        )
        image = BeautifulSoup(
            '<img src="placeholder.jpg" srcset="'
            "https://media.example.com/photos/id/master/w_120,c_limit/Album-Art.jpg 120w, "
            f'{largest} 1600w">',
            "html.parser",
        ).img

        self.assertEqual(
            normalize_image_source(image, "https://example.com/article"), largest
        )

    def test_extract_article_recovers_lazy_image_from_embedded_json(self) -> None:
        embedded_html = (
            '<p><img alt="Dungeon Map" '
            f'src="{IGN_IMAGE_URL}" srcset="{IGN_IMAGE_URL} 1024w"></p>'
        )
        page_html = f"""
        <html>
          <head><title>Lazy Images</title></head>
          <body>
            <article>
              <h1>Lazy Images</h1>
              <p>This article has enough readable text to preserve its content.</p>
              <button title="Click to Show">
                <img alt="Dungeon Map" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAA">
              </button>
            </article>
            <script id="__NEXT_DATA__" type="application/json">
              {json.dumps({"props": {"html": embedded_html}})}
            </script>
          </body>
        </html>
        """

        article = extract_article(page_html, "https://example.com/story")

        self.assertIn(IGN_IMAGE_URL.replace("&", "&amp;"), article.content_html)
        self.assertNotIn("data:image", article.content_html)

    def test_extract_article_recovers_sections_truncated_by_readability(self) -> None:
        sections = "".join(
            f"""
            <section>
              <h2>Album {rank}</h2>
              <p>This is the complete review for ranked album {rank}.</p>
              <img src="/covers/{rank}.jpg" alt="Album {rank} cover">
            </section>
            """
            for rank in range(8, 0, -1)
        )
        page_html = f"""
        <html>
          <head><meta property="og:title" content="Eight Best Albums"></head>
          <body>
            <nav>Unrelated navigation</nav>
            <article><h1>Eight Best Albums</h1>{sections}</article>
          </body>
        </html>
        """
        truncated_html = """
        <div>
          <h2>Album 8</h2><p>This is the complete review for ranked album 8.</p>
          <h2>Album 7</h2><p>This is the complete review for ranked album 7.</p>
        </div>
        """

        with patch("articles.extract_articles.Document") as document_class:
            document_class.return_value.summary.return_value = truncated_html
            article = extract_article(page_html, "https://example.com/best-albums")

        self.assertEqual(article.content_html.count("<h2>"), 8)
        self.assertIn("complete review for ranked album 1", article.content_html)
        self.assertIn("https://example.com/covers/1.jpg", article.content_html)
        self.assertNotIn("Unrelated navigation", article.content_html)

    def test_explicit_body_excludes_conversation_page_furniture(self) -> None:
        # Synthetic fixture matching the inspected Conversation page structure.
        page_html = """
        <html><head><meta property="og:title" content="AI hallucinations">
        <meta name="author" content="Example Author"></head><body><article>
        <h1>AI hallucinations</h1>
        <figure><img src="/decorative-hero.jpg"></figure>
        <div class="content-body entry-content" itemprop="articleBody">
          <p>Opening explanation with an <a href="/research">inline citation</a>.</p>
          <h2>Making it up</h2><p>Important first section.</p>
          <div class="newsletter-signup"><h3>Subscribe</h3><p>Promotion.</p></div>
          <h2>What causes hallucinations</h2>
          <figure><button><img data-src="/diagram.png" alt="Useful diagram"></button>
          <figcaption>Diagram explanation and credit.</figcaption></figure>
          <h2>What’s at risk</h2><p>Important risks.</p>
          <h2>Check AI’s work</h2><p>The complete final paragraph.</p>
        </div>
        <div class="topic-list"><h3>Topics</h3><ul><li>AI tags</li></ul></div>
        <aside class="content-sidebar"><h3>Authors</h3><p>Author biography.</p>
          <img src="/author.jpg"><h3>Disclosure statement</h3><p>Disclosure.</p>
          <h3>Partners</h3><h3>Languages</h3><h3>DOI</h3></aside>
        </article><footer>Site footer</footer></body></html>
        """
        article = extract_article(page_html, "https://example.com/story")
        body = BeautifulSoup(article.content_html, "html.parser")
        self.assertEqual(len(body.select("h2")), 4)
        self.assertIn("The complete final paragraph.", body.get_text())
        self.assertIn("Diagram explanation and credit.", body.get_text())
        self.assertEqual(body.img["src"], "https://example.com/diagram.png")
        self.assertEqual(len(body.select("img")), 1)
        self.assertEqual(body.a["href"], "https://example.com/research")
        self.assertEqual(article.byline, "Example Author")
        for clutter in ("Topics", "Authors", "Disclosure", "Partners", "Languages",
                        "DOI", "Subscribe", "Promotion", "Site footer"):
            self.assertNotIn(clutter, body.get_text())

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "clean.md"
            render_markdown([article], output, FakeDownloader(png_bytes()),
                            include_images=True, download_images=False)
            markdown = output.read_text()
            self.assertIn("The complete final paragraph.", markdown)
            self.assertNotIn("Author biography", markdown)
            self.assertNotIn("Promotion", markdown)

    def test_sidebar_headings_do_not_trigger_full_article_recovery(self) -> None:
        page_html = """
        <html><head><meta property="og:title" content="A story"></head><body>
        <article><div><h2>Story section</h2><p>Keep the article prose.</p></div>
        <div>Unmarked surrounding junk must not be restored.</div>
        <aside class="content-sidebar"><h3>Authors</h3><h3>Partners</h3>
        <h3>Languages</h3><h3>Disclosure</h3></aside></article></body></html>
        """
        readable = "<div><h2>Story section</h2><p>Keep the article prose.</p></div>"
        with patch("articles.extract_articles.Document") as document_class:
            document_class.return_value.summary.return_value = readable
            article = extract_article(page_html, "https://example.com/story")
        self.assertIn("Keep the article prose.", article.content_html)
        self.assertNotIn("surrounding junk", article.content_html)

    def test_recovery_removes_promos_but_preserves_editorial_asides(self) -> None:
        sections = "".join(f"<h2>Section {i}</h2><p>Full section {i}.</p>"
                           for i in range(6))
        page_html = f"""<html><head><meta property="og:title" content="Story"></head>
        <body><article>{sections}
        <aside><p>Editorial context about newsletters and related articles.</p></aside>
        <div class="related-articles"><h2>Suggested reading</h2><p>Other story.</p></div>
        <footer>Share this story.</footer></article></body></html>"""
        with patch("articles.extract_articles.Document") as document_class:
            document_class.return_value.summary.return_value = "<p>Full section 0.</p>"
            article = extract_article(page_html, "https://example.com/story")
        self.assertEqual(article.content_html.count("<h2>"), 6)
        self.assertIn("Editorial context", article.content_html)
        self.assertNotIn("Other story", article.content_html)
        self.assertNotIn("Share this story", article.content_html)

    def test_empty_or_ambiguous_explicit_body_uses_readability(self) -> None:
        for marker in ('<div itemprop="articleBody"></div>',
                       '<meta itemprop="articleBody" content="Summary">',
                       '<div itemprop="articleBody"><p>First story</p></div>'
                       '<div itemprop="articleBody"><p>Second story</p></div>'):
            with self.subTest(marker=marker):
                page_html = '<head><meta property="og:title" content="Story"></head>' + marker
                with patch("articles.extract_articles.Document") as document_class:
                    document_class.return_value.summary.return_value = "<p>Selected story.</p>"
                    article = extract_article(page_html, "https://example.com/story")
                self.assertIn("Selected story.", article.content_html)

    def test_render_markdown_downloads_image_into_assets_folder(self) -> None:
        article = extract_article(SAMPLE_HTML, "https://example.com/story")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "article.md"
            warnings = render_markdown(
                [article], output, FakeDownloader(png_bytes()), include_images=True
            )
            content = output.read_text(encoding="utf-8")
            assets = list((Path(directory) / "article_assets").glob("*.jpg"))

            self.assertEqual(warnings, [])
            self.assertIn("# Example Article", content)
            self.assertEqual(content.count("# Example Article"), 1)
            self.assertIn("article_assets/", content)
            self.assertEqual(len(assets), 1)

    def test_render_markdown_can_keep_remote_image_urls(self) -> None:
        article = Article(
            title="Remote Image",
            source_url="https://example.com/story",
            content_html=f'<p><img src="{IGN_IMAGE_URL}" alt=""></p>',
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "article.md"
            warnings = render_markdown(
                [article],
                output,
                FailingDownloader(),
                include_images=True,
                download_images=False,
            )

            self.assertEqual(warnings, [])
            self.assertIn(f"![]({IGN_IMAGE_URL})", output.read_text(encoding="utf-8"))
            self.assertFalse((Path(directory) / "article_assets").exists())

    def test_failed_markdown_download_falls_back_to_remote_url(self) -> None:
        article = Article(
            title="Remote Image",
            source_url="https://example.com/story",
            content_html=f'<p><img src="{IGN_IMAGE_URL}" alt=""></p>',
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "article.md"
            warnings = render_markdown(
                [article], output, FailingDownloader(), include_images=True
            )

            self.assertEqual(len(warnings), 1)
            self.assertIn(f"![]({IGN_IMAGE_URL})", output.read_text(encoding="utf-8"))

    def test_render_pdf_contains_article_text_and_embedded_image(self) -> None:
        article = extract_article(SAMPLE_HTML, "https://example.com/story")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "article.pdf"
            warnings = render_pdf(
                [article],
                output,
                FakeDownloader(png_bytes()),
                include_images=True,
                temp_root=root / "tmp",
            )
            reader = PdfReader(output)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)

            self.assertEqual(warnings, [])
            self.assertIn("Example Article", text)
            self.assertIn("opening paragraph", text)
            self.assertGreater(output.stat().st_size, 1_000)

    def test_render_pdf_uses_selected_page_sizes(self) -> None:
        article = extract_article(SAMPLE_HTML, "https://example.com/story")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("LETTER", "LEGAL", "GOV_LEGAL", "A4", "B5"):
                with self.subTest(page_size=name):
                    output = root / f"article-{name}.pdf"
                    render_pdf(
                        [article],
                        output,
                        FakeDownloader(png_bytes()),
                        include_images=True,
                        temp_root=root / "tmp",
                        page_size=PAGE_SIZES[name],
                    )
                    page = PdfReader(output).pages[0]
                    self.assertAlmostEqual(
                        float(page.mediabox.width), PAGE_SIZES[name][0], places=2
                    )
                    self.assertAlmostEqual(
                        float(page.mediabox.height), PAGE_SIZES[name][1], places=2
                    )

    def test_render_pdf_uses_custom_page_size_in_inches(self) -> None:
        article = extract_article(SAMPLE_HTML, "https://example.com/story")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "article-custom.pdf"
            custom_page_size = resolve_page_size("6.5x9")
            custom_margins = PDFMargins(top=36, right=36, bottom=36, left=36)
            render_pdf(
                [article],
                output,
                FakeDownloader(png_bytes()),
                include_images=True,
                temp_root=root / "tmp",
                page_size=custom_page_size,
                margins=custom_margins,
            )
            page = PdfReader(output).pages[0]
            self.assertAlmostEqual(float(page.mediabox.width), 6.5 * 72, places=2)
            self.assertAlmostEqual(float(page.mediabox.height), 9 * 72, places=2)

    def test_render_pdf_applies_custom_margins(self) -> None:
        article = extract_article(SAMPLE_HTML, "https://example.com/story")
        margins = PDFMargins(top=36, right=45, bottom=54, left=63)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("articles.extract_articles.SimpleDocTemplate") as template:
                render_pdf(
                    [article],
                    root / "article-margins.pdf",
                    FakeDownloader(png_bytes()),
                    include_images=False,
                    temp_root=root / "tmp",
                    margins=margins,
                )

        _, kwargs = template.call_args
        self.assertEqual(kwargs["topMargin"], margins.top)
        self.assertEqual(kwargs["rightMargin"], margins.right)
        self.assertEqual(kwargs["bottomMargin"], margins.bottom)
        self.assertEqual(kwargs["leftMargin"], margins.left)

    def test_failed_pdf_image_download_adds_clickable_source_link(self) -> None:
        article = Article(
            title="Remote Image",
            source_url="https://example.com/story",
            content_html=f'<p><img src="{IGN_IMAGE_URL}" alt=""></p>',
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "article.pdf"
            warnings = render_pdf(
                [article],
                output,
                FailingDownloader(),
                include_images=True,
                temp_root=root / "tmp",
            )
            reader = PdfReader(output)
            annotations = reader.pages[0].get("/Annots", [])
            urls = [
                annotation.get_object()["/A"]["/URI"]
                for annotation in annotations
                if annotation.get_object().get("/A")
            ]

            self.assertEqual(len(warnings), 1)
            self.assertIn(IGN_IMAGE_URL, urls)


if __name__ == "__main__":
    unittest.main()
