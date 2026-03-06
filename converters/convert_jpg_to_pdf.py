import os
from PIL import Image

def convert_jpgs_to_pdfs(directory="."):
    """
    Finds all .jpg and .jpeg files in the given directory and converts them to .pdf.
    """
    # List all files in the directory
    files = [f for f in os.listdir(directory) if f.lower().endswith((".jpg", ".jpeg"))]
    
    if not files:
        print("No JPG/JPEG files found.")
        return

    for jpg_file in files:
        jpg_path = os.path.join(directory, jpg_file)
        pdf_name = os.path.splitext(jpg_file)[0] + ".pdf"
        pdf_path = os.path.join(directory, pdf_name)
        
        try:
            # Open the image and convert it to RGB (required for PDF saving)
            with Image.open(jpg_path) as img:
                rgb_img = img.convert("RGB")
                rgb_img.save(pdf_path, "PDF")
                print(f"Converted: {jpg_file} -> {pdf_name}")
        except Exception as e:
            print(f"Error converting {jpg_file}: {e}")

if __name__ == "__main__":
    convert_jpgs_to_pdfs()
