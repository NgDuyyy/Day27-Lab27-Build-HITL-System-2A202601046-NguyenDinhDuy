"""
app.py — Streamlit Approval Interface cho hệ thống HITL.

Chạy:
    streamlit run app.py

Chức năng:
- Nhập Customer ID và chọn scenario
- Invoke LangGraph → hiển thị Agent reasoning
- Nếu graph bị interrupt → hiển thị Action Card + 3 buttons (Approve/Reject/Edit)
- Resume graph sau human decision
- Hiển thị Audit Log history
"""

import json
import os

import streamlit as st

from graph import AUDIT_LOG_PATH, MOCK_CUSTOMERS, build_graph

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="HITL Approval Dashboard",
    page_icon="🛡️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Khởi tạo graph trong session_state (tránh tạo lại mỗi lần rerun)
# ---------------------------------------------------------------------------
if "graph" not in st.session_state:
    st.session_state.graph = build_graph()

if "thread_counter" not in st.session_state:
    st.session_state.thread_counter = 0

if "current_result" not in st.session_state:
    st.session_state.current_result = None

if "is_interrupted" not in st.session_state:
    st.session_state.is_interrupted = False

if "config" not in st.session_state:
    st.session_state.config = None

if "action_taken" not in st.session_state:
    st.session_state.action_taken = None

graph = st.session_state.graph

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🛡️ Human-in-the-Loop Approval Dashboard")
st.markdown(
    "Hệ thống review quyết định của AI Agent trước khi thực thi các hành động high-risk."
)
st.divider()

# ---------------------------------------------------------------------------
# Sidebar — Customer Input
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("📋 Customer Input")

    customer_id = st.selectbox(
        "Chọn Customer ID",
        options=list(MOCK_CUSTOMERS.keys()) + ["CUST_NEW"],
        help="Chọn customer để agent đánh giá",
    )

    if customer_id in MOCK_CUSTOMERS:
        cust = MOCK_CUSTOMERS[customer_id]
        st.info(
            f"**{cust['name']}**\n\n"
            f"- TOI: {cust['toi']:,} VND\n"
            f"- Churn Prob: {cust['churn_probability']}\n"
            f"- Tenure: {cust['tenure_months']} months"
        )
    else:
        st.warning("Customer không có trong database → agent sẽ đề xuất safe action.")

    st.divider()

    if st.button("🚀 Evaluate Customer", type="primary", use_container_width=True):
        # Tạo thread mới mỗi lần evaluate
        st.session_state.thread_counter += 1
        thread_id = f"thread_{st.session_state.thread_counter}"
        config = {"configurable": {"thread_id": thread_id}}
        st.session_state.config = config

        # Reset state
        st.session_state.is_interrupted = False
        st.session_state.action_taken = None

        # Invoke graph
        initial_state = {
            "customer_id": customer_id,
            "proposed_action": "",
            "confidence_score": 0.0,
            "reasoning": "",
            "human_decision": None,
        }

        result = graph.invoke(initial_state, config)
        st.session_state.current_result = result

        # Kiểm tra graph có bị interrupt không
        state_snapshot = graph.get_state(config)
        if state_snapshot.next:
            # Graph đang ở trạng thái pending (interrupted trước execute_high_risk_action)
            st.session_state.is_interrupted = True
        else:
            st.session_state.is_interrupted = False

        st.rerun()

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

if st.session_state.current_result is not None:
    result = st.session_state.current_result
    config = st.session_state.config

    # Lấy state hiện tại từ graph
    state_snapshot = graph.get_state(config)
    current_state = state_snapshot.values

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📊 Agent Reasoning Output")

        # Action Card
        action_type = current_state.get("proposed_action", "unknown")
        confidence = current_state.get("confidence_score", 0.0)
        reasoning = current_state.get("reasoning", "")

        # Colour code theo risk level
        if action_type == "increase_credit_limit":
            st.error("⚠️ **HIGH-RISK ACTION**")
        else:
            if confidence >= 0.85:
                st.success("✅ **LOW-RISK ACTION** — Auto-executable")
            else:
                st.warning("⚡ **LOW-RISK ACTION** — Confidence thấp, cần review")

        st.markdown(
            f"""
| Trường | Giá trị |
|--------|---------|
| **Customer ID** | `{current_state.get('customer_id', 'N/A')}` |
| **Proposed Action** | `{action_type}` |
| **Confidence Score** | `{confidence}` |
| **Reasoning** | {reasoning} |
"""
        )

    with col2:
        st.subheader("📈 Confidence Meter")
        st.metric(
            label="Confidence Score",
            value=f"{confidence:.0%}",
            delta="High" if confidence >= 0.85 else "Low",
            delta_color="normal" if confidence >= 0.85 else "inverse",
        )
        st.progress(confidence)

    st.divider()

    # ----- Trường hợp 1: Graph đã bị interrupt → cần human review -----
    if st.session_state.is_interrupted and st.session_state.action_taken is None:
        st.subheader("🧑‍⚖️ Human Review Required")
        st.warning(
            "Graph đã dừng trước `execute_high_risk_action`. "
            "Vui lòng review và chọn hành động bên dưới."
        )

        # Edit field — cho phép human chỉnh sửa proposed action
        edited_action = st.text_input(
            "✏️ Edit proposed action (nếu cần)",
            value=current_state.get("proposed_action", ""),
            key="edit_action",
        )

        # 3 buttons
        btn_col1, btn_col2, btn_col3 = st.columns(3)

        with btn_col1:
            if st.button("✅ Approve", type="primary", use_container_width=True):
                graph.update_state(config, {"human_decision": "approve"})
                final_result = graph.invoke(None, config)
                st.session_state.current_result = final_result
                st.session_state.is_interrupted = False
                st.session_state.action_taken = "approve"
                st.rerun()

        with btn_col2:
            if st.button("❌ Reject", type="secondary", use_container_width=True):
                graph.update_state(config, {"human_decision": "reject"})
                final_result = graph.invoke(None, config)
                st.session_state.current_result = final_result
                st.session_state.is_interrupted = False
                st.session_state.action_taken = "reject"
                st.rerun()

        with btn_col3:
            if st.button("✏️ Edit & Approve", type="secondary", use_container_width=True):
                graph.update_state(
                    config,
                    {
                        "human_decision": "edit",
                        "proposed_action": edited_action,
                    },
                )
                final_result = graph.invoke(None, config)
                st.session_state.current_result = final_result
                st.session_state.is_interrupted = False
                st.session_state.action_taken = "edit"
                st.rerun()

    # ----- Trường hợp 2: Đã có action (human đã quyết định hoặc auto-execute) -----
    elif st.session_state.action_taken is not None or not st.session_state.is_interrupted:
        st.subheader("📋 Execution Result")

        decision = current_state.get("human_decision", "N/A")

        if decision == "auto_approved":
            st.success(
                "🤖 **Auto-Executed** — Action low-risk với confidence cao, "
                "đã tự động thực thi mà không cần human review."
            )
        elif decision == "approve":
            st.success("✅ **Approved** — Action đã được human operator phê duyệt và thực thi.")
        elif decision == "reject":
            st.error("❌ **Rejected** — Action đã bị human operator từ chối. Không thực thi.")
        elif decision == "edit":
            st.info(
                f"✏️ **Edited & Approved** — Action đã được chỉnh sửa thành "
                f"`{current_state.get('proposed_action', 'N/A')}` và thực thi."
            )
        else:
            st.info(f"Decision: `{decision}`")

# ---------------------------------------------------------------------------
# Audit Log Viewer
# ---------------------------------------------------------------------------
st.divider()
st.subheader("📜 Audit Log History")

if os.path.exists(AUDIT_LOG_PATH):
    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        try:
            logs = json.load(f)
        except json.JSONDecodeError:
            logs = []

    if logs:
        # Hiển thị bảng ngược (mới nhất trước)
        st.dataframe(
            list(reversed(logs)),
            use_container_width=True,
            column_config={
                "timestamp": st.column_config.TextColumn("Timestamp"),
                "agent_id": st.column_config.TextColumn("Agent"),
                "action": st.column_config.TextColumn("Action"),
                "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                "reviewer_id": st.column_config.TextColumn("Reviewer"),
                "decision": st.column_config.TextColumn("Decision"),
            },
        )
    else:
        st.info("Chưa có audit entry nào. Hãy evaluate một customer để bắt đầu.")
else:
    st.info("File `audit_log.json` chưa tồn tại. Hãy evaluate một customer để bắt đầu.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "Day 27 — Build HITL System | LangGraph + Streamlit | "
    "2A202601046 — Nguyễn Đình Duy"
)
