class TailorValidationError(Exception):
    """Raised when the model's manifest fails validation against the resume bank."""


class ClaudeCliError(Exception):
    """Raised when the `claude` CLI invocation fails (not found, timeout, non-zero exit, bad output)."""


class PdfCompileError(Exception):
    """Raised when pdflatex fails to produce a PDF."""


class CannotFitOnePageError(Exception):
    """Raised when the resume still exceeds one page after exhausting all trims."""


class SheetsError(Exception):
    """Raised when the applications sheet cannot be read.

    Its message MUST NOT contain APPS_SCRIPT_URL or APPS_SCRIPT_READ_SECRET —
    it is surfaced to clients (as a 502) and may be logged.
    """
