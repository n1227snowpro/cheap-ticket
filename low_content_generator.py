#!/usr/bin/env python3
"""
Low-Content Book Generator
Duplicates a single page image (JPG/PNG) N times into a PDF file.

Usage:
    python3 book_generator.py input.jpg
    python3 book_generator.py input.png --pages 50
    python3 book_generator.py input.jpg --pages 120 --output my_book.pdf
"""

import argparse
import sys
from pathlib import Path
from PIL import Image


def generate_book(input_path: str, num_pages: int, output_path=None) -> str:
    input_file = Path(input_path)

    if not input_file.exists():
        print(f"Error: File '{input_path}' not found.")
        sys.exit(1)

    if input_file.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        print(f"Error: Input must be a JPG or PNG file. Got: '{input_file.suffix}'")
        sys.exit(1)

    if num_pages < 1:
        print(f"Error: Number of pages must be at least 1. Got: {num_pages}")
        sys.exit(1)

    if output_path is None:
        output_path = str(input_file.with_name(f"{input_file.stem}_{num_pages}pages.pdf"))

    print(f"  Input image : {input_path}")
    print(f"  Pages       : {num_pages}")
    print(f"  Output PDF  : {output_path}")
    print()

    # Open and convert image to RGB (required for PDF save)
    img = Image.open(input_path).convert("RGB")

    # Build the list of duplicated pages
    print(f"Generating {num_pages} pages...", end="", flush=True)
    pages = [img.copy() for _ in range(num_pages - 1)]
    print(" done.")

    print("Saving PDF...", end="", flush=True)
    img.save(
        output_path,
        format="PDF",
        save_all=True,
        append_images=pages,
        resolution=150,  # DPI — adjust if needed
    )
    print(" done.")

    print(f"\nBook saved to: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Generate a low-content book PDF by duplicating a single page image.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 book_generator.py page.jpg
  python3 book_generator.py page.png --pages 50
  python3 book_generator.py page.jpg --pages 120 --output journal.pdf
        """,
    )
    parser.add_argument("input", help="Input image file (JPG or PNG)")
    parser.add_argument(
        "--pages", "-p",
        type=int,
        default=100,
        metavar="N",
        help="Number of pages to generate (default: 100)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        metavar="FILE",
        help="Output PDF filename (default: <input_name>_<N>pages.pdf)",
    )

    args = parser.parse_args()
    generate_book(args.input, args.pages, args.output)


if __name__ == "__main__":
    main()
