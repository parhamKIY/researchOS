from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def scientific_fixture(path: Path, *, scanned=False, pages=2):
    output = canvas.Canvas(str(path), pagesize=(400, 600))
    output.setTitle("Synthetic document extraction fixture")
    output.setAuthor("ResearchOS fixture author")
    for index in range(pages):
        if not scanned:
            output.setFont("Helvetica", 14)
            output.drawString(30, 560, "1 Introduction" if index == 0 else "2 Methods")
            output.setFont("Helvetica", 11)
            output.drawString(30, 530, "This is synthetic source text, not a scientific finding.")
            output.drawString(30, 510, "Reference candidate: 10.1234/fixture.example")
            output.drawString(30, 260, "Figure 1: Synthetic embedded raster fixture.")
        image = Image.new("RGB", (100, 80), color=(34, 90, 67))
        output.drawImage(ImageReader(image), 30, 300, width=100, height=80)
        output.showPage()
    output.save()
