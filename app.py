#!/usr/bin/env python3
"""
Low-Content Book Generator — Web UI backend
Run: python3 app.py
Then open: http://localhost:5000
"""

import io
import os
from flask import Flask, render_template, request, send_file, jsonify
from PIL import Image

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    if "image" not in request.files:
        return jsonify({"error": "No image file uploaded."}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        return jsonify({"error": "Only JPG and PNG files are supported."}), 400

    try:
        num_pages = int(request.form.get("pages", 100))
        if num_pages < 1 or num_pages > 1000:
            return jsonify({"error": "Pages must be between 1 and 1000."}), 400
    except ValueError:
        return jsonify({"error": "Invalid page count."}), 400

    output_name = request.form.get("output_name", "").strip()
    if not output_name:
        base = os.path.splitext(file.filename)[0]
        output_name = f"{base}_{num_pages}pages"
    if not output_name.endswith(".pdf"):
        output_name += ".pdf"

    try:
        img = Image.open(file.stream).convert("RGB")
        pages = [img.copy() for _ in range(num_pages - 1)]

        pdf_buffer = io.BytesIO()
        img.save(
            pdf_buffer,
            format="PDF",
            save_all=True,
            append_images=pages,
            resolution=150,
        )
        pdf_buffer.seek(0)

        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=output_name,
        )
    except Exception as e:
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=9000)
