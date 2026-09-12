import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

from converters.combine_images_to_pdf import combine_images_to_pdf


class CombineImagesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def make_image(self, name, size=(20, 30), mode="RGB", color="red", **kwargs):
        with Image.new(mode, size, color) as image:
            image.save(self.folder / name, **kwargs)

    def test_mixed_formats_natural_order_orientation_and_transparency(self):
        self.make_image("image10.bmp", (40, 50))
        self.make_image("image2.PNG", (30, 40), "RGBA", (0, 0, 0, 0))
        exif = Image.Exif()
        exif[274] = 6
        self.make_image("image1.jpg", (20, 30), exif=exif)
        (self.folder / "notes.txt").write_text("Not an image")
        output, count = combine_images_to_pdf(self.folder)
        pages = PdfReader(output).pages
        self.assertEqual(count, 3)
        self.assertEqual(
            [(float(p.mediabox.width), float(p.mediabox.height)) for p in pages],
            [(30, 20), (30, 40), (40, 50)],
        )
        self.assertEqual(pages[1].images[0].image.convert("RGB").getpixel((0, 0)), (255, 255, 255))

    def test_subfolders_are_opt_in(self):
        (self.folder / "nested").mkdir()
        self.make_image("image.png")
        self.make_image("nested/image.png")
        output, count = combine_images_to_pdf(self.folder)
        self.assertEqual(count, 1)
        _, count = combine_images_to_pdf(self.folder, recursive=True, overwrite=True)
        self.assertEqual(count, 2)
        self.assertEqual(len(PdfReader(output).pages), 2)

    def test_existing_output_requires_overwrite_and_survives_failure(self):
        self.make_image("image1.png")
        output, _ = combine_images_to_pdf(self.folder)
        original = output.read_bytes()
        with self.assertRaises(FileExistsError):
            combine_images_to_pdf(self.folder)
        (self.folder / "image2.jpg").write_bytes(b"invalid image")
        with self.assertRaisesRegex(ValueError, "image2.jpg"):
            combine_images_to_pdf(self.folder, overwrite=True)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(len(list(self.folder.glob("*.pdf"))), 1)

    def test_empty_invalid_folder_and_output(self):
        with self.assertRaisesRegex(ValueError, "No supported images"):
            combine_images_to_pdf(self.folder)
        with self.assertRaisesRegex(ValueError, "Not a folder"):
            combine_images_to_pdf(self.folder / "missing")
        self.make_image("image.png")
        with self.assertRaisesRegex(ValueError, "must end in .pdf"):
            combine_images_to_pdf(self.folder, self.folder / "image.png", overwrite=True)

    def test_animated_image_uses_first_frame(self):
        with Image.new("RGB", (20, 30), "red") as first:
            with Image.new("RGB", (20, 30), "blue") as second:
                first.save(self.folder / "animated.gif", save_all=True, append_images=[second])
        output, count = combine_images_to_pdf(self.folder)
        self.assertEqual(count, 1)
        pages = PdfReader(output).pages
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].images[0].image.convert("RGB").getpixel((0, 0)), (255, 0, 0))

    def test_cli_custom_output_and_error_exit(self):
        self.make_image("image.png")
        script = Path(__file__).resolve().parents[1] / "converters/combine_images_to_pdf.py"
        output = self.folder / "custom album.pdf"
        command = [sys.executable, str(script), str(self.folder), "-o", str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(PdfReader(output).pages), 1)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stderr)


if __name__ == "__main__":
    unittest.main()
