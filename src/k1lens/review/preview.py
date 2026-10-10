"""Render the first PDF page to a PNG so the review pane is not a black frame."""

from __future__ import annotations

import io


def pdf_preview_png(payload: bytes) -> bytes:
    import pypdfium2 as pdfium
    from pypdfium2 import PdfiumError

    if not payload:
        raise ValueError("empty pdf")
    try:
        pdf = pdfium.PdfDocument(payload)
    except PdfiumError as exc:
        raise ValueError("pdf preview failed") from exc
    try:
        if len(pdf) == 0:
            raise ValueError("pdf has no pages")
        page = pdf[0]
        image = page.render(scale=2).to_pil().convert("RGB")
    except PdfiumError as exc:
        raise ValueError("pdf preview failed") from exc
    finally:
        pdf.close()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
