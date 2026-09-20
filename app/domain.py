"""Core domain types and rules."""
from dataclasses import dataclass
from enum import Enum

class Decision(str, Enum):
    PERMIT = "permit"
    APPROVAL = "approval"
    DENY = "deny"

@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str = ""