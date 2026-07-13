import tempfile
import unittest
from pathlib import Path

from PIL import Image as PillowImage
from pypdf import PdfReader

from articles.extract_articles import (
    Article,
    PAGE_SIZES,
    extract_article,
    extract_urls_from_text,
    parse_args,
    render_markdown,
    render_pdf,
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


class FakeDownloader:
    def __init__(self, image_bytes: bytes) -> None:
        self.image_bytes = image_bytes

    def fetch_image(self, url: str) -> tuple[bytes, str]:
        return self.image_bytes, "image/png"


def png_bytes() -> bytes:
    import io

    buffer = io.BytesIO()
    PillowImage.new("RGB", (320, 180), "#4b70a8").save(buffer, "PNG")
    return buffer.getvalue()


class ArticleExtractorTests(unittest.TestCase):
    def test_page_size_argument_is_case_insensitive(self) -> None:
        args = parse_args(["https://example.com/story", "--page-size", "a4"])
        self.assertEqual(args.page_size, "A4")

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
            for name in ("LETTER", "A3", "A4", "A5"):
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


if __name__ == "__main__":
    unittest.main()
