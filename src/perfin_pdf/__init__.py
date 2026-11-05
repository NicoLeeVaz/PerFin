"""Optional, local-only PDF statement staging. No database or file writes."""
from .parser import LAYOUT_ID, PdfRefused, Extraction, extract_pdf
from .staging import PdfStageResult, stage_pdf

__version__ = "0.1.0"
__all__ = ["LAYOUT_ID", "PdfRefused", "Extraction", "extract_pdf", "PdfStageResult", "stage_pdf"]
