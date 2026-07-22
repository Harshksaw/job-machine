class TailorValidationError(Exception):
    """Raised when the model's manifest fails validation against the resume bank."""


class PdfCompileError(Exception):
    """Raised when pdflatex fails to produce a PDF."""


class CannotFitOnePageError(Exception):
    """Raised when the resume still exceeds one page after exhausting all trims."""
