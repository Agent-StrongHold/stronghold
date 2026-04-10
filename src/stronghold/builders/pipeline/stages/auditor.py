"""AuditorStage: verdict parsing for the Builders auditor review.

Extracted from RuntimePipeline.auditor_review to enable isolated testing
of the verdict parsing logic (APPROVED/CHANGES_REQUESTED detection).
"""

from __future__ import annotations

import logging
from typing import Any

auditor_logger = logging.getLogger("stronghold.builders.auditor")


def parse_verdict(text: str) -> bool:
    """Parse auditor verdict from LLM response text.

    Returns True (approved) or False (changes requested).
    Defaults to True if no verdict keyword found.
    """
    approved = True  # default approve if no verdict found
    for line in (text or "").splitlines():
        stripped = line.strip().upper().lstrip("#").strip()
        if stripped.startswith("APPROVED") or stripped.startswith("VERDICT: APPROVED") or stripped.startswith("VERDICT:APPROVED"):
            approved = True
            break
        if stripped.startswith("CHANGES_REQUESTED") or stripped.startswith("VERDICT: CHANGES") or stripped.startswith("VERDICT:CHANGES"):
            approved = False
            break
    return approved
