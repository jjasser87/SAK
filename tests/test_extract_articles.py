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
    extract_article,
    extract_urls_from_text,
    normalize_image_source,
    parse_args,
    pdf_styles,
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

    def test_scale_argument_accepts_scale_and_zoom_names(self) -> None:
        scale_args = parse_args(
            ["https://example.com/story", "--scale", "85"]
        )
        zoom_args = parse_args(
            ["https://example.com/story", "--zoom-scale", "125.5"]
        )

        self.assertEqual(scale_args.scale, 85)
        self.assertEqual(zoom_args.scale, 125.5)

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
