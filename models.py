"""
models.py — Pydantic schema cho Audit Trail.

AuditEntry ghi lại đầy đủ mọi quyết định:
- Agent nào đưa ra đề xuất?
- Hành động đề xuất là gì?
- Confidence bao nhiêu?
- Ai review?
- Human quyết định gì?
- Thời điểm nào?
"""

from pydantic import BaseModel


class AuditEntry(BaseModel):
    """Một entry trong audit trail — ghi lại quyết định của agent và human reviewer."""

    timestamp: str
    agent_id: str
    action: str
    confidence: float
    reviewer_id: str
    decision: str
