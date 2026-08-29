"""
graph.py — LangGraph workflow cho hệ thống HITL (Human-in-the-Loop).

Bao gồm:
- GraphState (TypedDict): persistent state xuyên suốt workflow
- evaluate_customer: Agent reasoning node (giả lập đánh giá TOI/churn)
- route_action: Conditional edge function với 3 rules (Policy Override, Auto-Execute, Escalate)
- execute_low_risk_action: Auto-execute cho low-risk actions
- execute_high_risk_action: Kiểm tra human_decision trước khi thực thi
- Graph compilation với MemorySaver + interrupt_before
"""

import json
import os
import random
from datetime import datetime
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from models import AuditEntry

# ---------------------------------------------------------------------------
# Bước 1: Định nghĩa GraphState
# ---------------------------------------------------------------------------


class GraphState(TypedDict):
    """State tồn tại xuyên suốt workflow, giữ proposed action trong khi chờ human approval."""

    customer_id: str
    proposed_action: str
    confidence_score: float
    reasoning: str
    human_decision: str | None


# ---------------------------------------------------------------------------
# Bước 2: Agent Reasoning Node
# ---------------------------------------------------------------------------

# Dữ liệu mock cho các customer
MOCK_CUSTOMERS = {
    "CUST001": {
        "name": "Nguyen Van A",
        "toi": 150_000_000,       # Total Operating Income
        "churn_probability": 0.7,  # cao → high-risk
        "tenure_months": 36,
    },
    "CUST002": {
        "name": "Tran Thi B",
        "toi": 50_000_000,
        "churn_probability": 0.3,  # thấp → low-risk
        "tenure_months": 12,
    },
    "CUST003": {
        "name": "Le Van C",
        "toi": 80_000_000,
        "churn_probability": 0.5,  # trung bình
        "tenure_months": 24,
    },
}


def evaluate_customer(state: GraphState) -> dict:
    """
    Giả lập Agent reasoning — đánh giá TOI và churn probability của khách hàng.

    Trả về:
    - proposed_action: "send_email" (low-risk) hoặc "increase_credit_limit" (high-risk)
    - confidence_score: 0.0 → 1.0
    - reasoning: lý do đề xuất
    """
    customer_id = state["customer_id"]
    customer = MOCK_CUSTOMERS.get(customer_id)

    if customer is None:
        # Customer không tồn tại → đề xuất low-risk action với confidence thấp
        return {
            "proposed_action": "send_email",
            "confidence_score": round(random.uniform(0.60, 0.80), 2),
            "reasoning": f"Customer {customer_id} not found in database. "
                         "Suggesting a generic retention email as a safe action.",
        }

    churn_prob = customer["churn_probability"]
    toi = customer["toi"]

    # Logic đánh giá:
    # - Churn probability cao (>= 0.6) VÀ TOI cao (>= 100M) → increase_credit_limit
    # - Ngược lại → send_email
    if churn_prob >= 0.6 and toi >= 100_000_000:
        proposed_action = "increase_credit_limit"
        confidence_score = round(random.uniform(0.88, 0.98), 2)
        reasoning = (
            f"Customer {customer['name']} has high churn probability ({churn_prob}) "
            f"and significant TOI ({toi:,} VND). "
            "Increasing the credit limit may help retain this high-value customer."
        )
    elif churn_prob >= 0.4:
        proposed_action = "send_email"
        confidence_score = round(random.uniform(0.78, 0.88), 2)
        reasoning = (
            f"Customer {customer['name']} has moderate churn probability ({churn_prob}). "
            "A personalized retention email is recommended as a low-risk intervention."
        )
    else:
        proposed_action = "send_email"
        confidence_score = round(random.uniform(0.88, 0.96), 2)
        reasoning = (
            f"Customer {customer['name']} has low churn probability ({churn_prob}) "
            "and no high-risk financial action is needed. "
            "Sending a standard follow-up email."
        )

    return {
        "proposed_action": proposed_action,
        "confidence_score": confidence_score,
        "reasoning": reasoning,
    }


# ---------------------------------------------------------------------------
# Bước 3: Confidence Routing + Hard Rules
# ---------------------------------------------------------------------------

# Threshold cho auto-execute
CONFIDENCE_THRESHOLD = 0.85

# Danh sách các action luôn cần human review (hard policy)
HIGH_RISK_ACTIONS = {"increase_credit_limit"}


def route_action(state: GraphState) -> str:
    """
    Conditional edge function — routing dựa trên 3 rules:

    Rule 1 — Policy Override:
        increase_credit_limit → luôn "execute_high_risk_action" (bất kể confidence)

    Rule 2 — Auto-Execute:
        action low-risk + confidence >= 0.85 → "execute_low_risk_action"

    Rule 3 — Escalate/Suggest:
        confidence < 0.85 → "execute_high_risk_action" (ép human review)
    """
    proposed_action = state["proposed_action"]
    confidence_score = state["confidence_score"]

    # Rule 1: Policy Override — hard rule luôn ưu tiên đầu tiên
    if proposed_action in HIGH_RISK_ACTIONS:
        return "execute_high_risk_action"

    # Rule 2: Auto-Execute — low-risk + high confidence
    if confidence_score >= CONFIDENCE_THRESHOLD:
        return "execute_low_risk_action"

    # Rule 3: Escalate — confidence thấp → cần human review
    return "execute_high_risk_action"


# ---------------------------------------------------------------------------
# Helper: Ghi Audit Log
# ---------------------------------------------------------------------------

AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "audit_log.json"
)


def _append_audit_log(entry: AuditEntry) -> None:
    """Append một AuditEntry vào audit_log.json mà KHÔNG ghi đè dữ liệu cũ."""
    # Đọc danh sách hiện có
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []
    else:
        logs = []

    # Append entry mới
    logs.append(entry.model_dump())

    # Ghi lại toàn bộ danh sách
    with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Node: Execute Low-Risk Action (auto-execute, không cần human review)
# ---------------------------------------------------------------------------


def execute_low_risk_action(state: GraphState) -> dict:
    """Auto-execute low-risk action và ghi audit log."""
    entry = AuditEntry(
        timestamp=datetime.now().isoformat(),
        agent_id="churn-risk-agent",
        action=state["proposed_action"],
        confidence=state["confidence_score"],
        reviewer_id="auto",
        decision="auto_approved",
    )
    _append_audit_log(entry)

    return {"human_decision": "auto_approved"}


# ---------------------------------------------------------------------------
# Node: Execute High-Risk Action (cần human review trước)
# ---------------------------------------------------------------------------


def execute_high_risk_action(state: GraphState) -> dict:
    """
    Kiểm tra human_decision và thực thi tương ứng:
    - approve: thực hiện action
    - reject: huỷ action
    - edit: thực hiện action đã chỉnh sửa

    Luôn ghi audit log.
    """
    decision = state.get("human_decision", "pending")

    entry = AuditEntry(
        timestamp=datetime.now().isoformat(),
        agent_id="churn-risk-agent",
        action=state["proposed_action"],
        confidence=state["confidence_score"],
        reviewer_id="operator_01",
        decision=decision,
    )
    _append_audit_log(entry)

    return {"human_decision": decision}


# ---------------------------------------------------------------------------
# Bước 4: Compile Graph với Interrupts
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    """Build và compile LangGraph StateGraph với MemorySaver + interrupt_before."""
    memory = MemorySaver()

    builder = StateGraph(GraphState)

    # Thêm các nodes
    builder.add_node("evaluate_customer", evaluate_customer)
    builder.add_node("execute_low_risk_action", execute_low_risk_action)
    builder.add_node("execute_high_risk_action", execute_high_risk_action)

    # Entry point
    builder.set_entry_point("evaluate_customer")

    # Conditional edge: evaluate_customer → route_action
    builder.add_conditional_edges(
        "evaluate_customer",
        route_action,
        {
            "execute_low_risk_action": "execute_low_risk_action",
            "execute_high_risk_action": "execute_high_risk_action",
        },
    )

    # Cả hai execution nodes → END
    builder.add_edge("execute_low_risk_action", END)
    builder.add_edge("execute_high_risk_action", END)

    # Compile với checkpointer và interrupt
    graph = builder.compile(
        checkpointer=memory,
        interrupt_before=["execute_high_risk_action"],
    )

    return graph
