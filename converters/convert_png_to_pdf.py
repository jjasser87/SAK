import os
import argparse
from PIL import Image

def convert_png_to_pdf(png_path):
    """
    Converts a single PNG file to PDF.
    """
    if not png_path.lower().endswith(".png"):
        print(f"Skipping {png_path}: Not a PNG file.")
        return

    pdf_path = os.path.splitext(png_path)[0] + ".pdf"
    
    try:
        # Open the image and convert it to RGB (required for PDF saving)
        with Image.open(png_path) as img:
            rgb_img = img.convert("RGB")
            rgb_img.save(pdf_path, "PDF")
            print(f"Converted: {png_path} -> {pdf_path}")
    except Exception as e:
        print(f"Error converting {png_path}: {e}")

def convert_pngs_in_directory(directory="."):
    """
    Finds all .png files in the given directory and converts them to .pdf.
    """
    files = [f for f in os.listdir(directory) if f.lower().endswith(".png")]
    
    if not files:
        print(f"No PNG files found in {directory}.")
        return

    for png_file in files:
        convert_png_to_pdf(os.path.join(directory, png_file))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert PNG images to PDF.")
    parser.add_argument(
        "path", 
        nargs="?", 
        default=".", 
        help="Path to a specific PNG file or a directory (defaults to current directory)."
    )
    
    args = parser.parse_args()
    
    if os.path.isfile(args.path):
        convert_png_to_pdf(args.path)
    elif os.path.isdir(args.path):
        convert_pngs_in_directory(args.path)
    else:
        print(f"Error: {args.path} is not a valid file or directory.")
