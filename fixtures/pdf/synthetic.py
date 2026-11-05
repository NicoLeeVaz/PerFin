"""Invented test PDF source; never a real bank statement. No binary stored in Git."""
from io import BytesIO
from reportlab.pdfgen.canvas import Canvas

TITLE = "PERFIN SYNTHETIC STATEMENT v1"
HEADER = "Date | Description | Debit | Credit"


def pages():
    return [
        [TITLE, "Currency: USD", "Opening: 1000.00", "Closing: 1170.00", "Transactions: 3", HEADER,
         "2026-07-01 | SYNTHETIC SHOP | 50.00 |", "> WRAPPED DESCRIPTION", "Page 1 of 2"],
        [TITLE, HEADER, HEADER, "2026-07-02 | SYNTHETIC REFUND | | 20.00",
         "2026-07-03 | SYNTHETIC DEPOSIT | | 200.00", "Page 2 of 2"],
    ]


def pdf_bytes(lines_by_page=None):
    out = BytesIO()
    canvas = Canvas(out, pagesize=(612, 792), pageCompression=0, invariant=1)
    canvas.setTitle("Synthetic PerFin parser fixture")
    for lines in (pages() if lines_by_page is None else lines_by_page):
        text = canvas.beginText(36, 752)
        text.setFont("Courier", 9)
        text.setLeading(17)
        for line in lines:
            text.textLine(line)
        canvas.drawText(text)
        canvas.showPage()
    canvas.save()
    return out.getvalue()
