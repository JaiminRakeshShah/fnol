"""Citations server: exact quotes from stored raw text and raw JSON.

Any quote containing private_token or SYNTHETIC-PRIVATE- is refused.
"""

from fnol_citations.guard import reject_restricted_quote
from fnol_citations.pipeline import start_citations
from fnol_citations.service import CitationError, run_citations

__all__ = [
    "CitationError",
    "reject_restricted_quote",
    "run_citations",
    "start_citations",
]
