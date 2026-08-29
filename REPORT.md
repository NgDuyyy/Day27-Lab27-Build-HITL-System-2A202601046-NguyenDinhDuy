# 📝 BÁO CÁO CÁ NHÂN — Lab 27: Build HITL System

> **Họ tên:** Nguyễn Đình Duy  
> **MSSV:** 2A202601046  
> **Ngày thực hiện:** 29/08/2026  
> **Track:** AI thực chiến — Track 3, Day 27

---

## 1. Tổng quan bài lab

### Mục tiêu
Xây dựng hệ thống **Human-in-the-Loop (HITL)** cho phép con người review và phê duyệt các quyết định high-risk của AI Agent trước khi thực thi, sử dụng **LangGraph** làm workflow engine và **Streamlit** làm giao diện dashboard.

### Bài toán
Trong lĩnh vực tài chính/ngân hàng, khi AI Agent đề xuất các hành động như **tăng hạn mức tín dụng** cho khách hàng có nguy cơ rời bỏ (churn) cao, quyết định này **không nên được thực thi tự động** mà cần có sự kiểm duyệt của con người. Hệ thống HITL đảm bảo:
- Hành động low-risk → tự động thực thi (giảm tải cho operator)
- Hành động high-risk → dừng lại, chờ human review
- Mọi quyết định đều được ghi nhận (audit trail) để truy vết

---

## 2. Các bước thực hiện

### Bước 1 — Định nghĩa State và Audit Schema

Tạo `GraphState` bằng `TypedDict` với 5 trường dữ liệu cần thiết:

```python
class GraphState(TypedDict):
    customer_id: str
    proposed_action: str      # "send_email" hoặc "increase_credit_limit"
    confidence_score: float   # 0.0 → 1.0
    reasoning: str            # lý do đề xuất
    human_decision: str | None  # approve / reject / edit / auto_approved
```

Định nghĩa `AuditEntry` bằng Pydantic `BaseModel` để validate dữ liệu audit:

```python
class AuditEntry(BaseModel):
    timestamp: str
    agent_id: str
    action: str
    confidence: float
    reviewer_id: str
    decision: str
```

**Nhận xét:** `GraphState` sử dụng `TypedDict` thay vì `BaseModel` vì LangGraph yêu cầu state phải là dict-like. Trường `human_decision` ban đầu là `None` và sẽ được cập nhật sau khi human review.

---

### Bước 2 — Implement Agent Reasoning Node

Tạo node `evaluate_customer()` giả lập agent reasoning dựa trên mock data:

```python
MOCK_CUSTOMERS = {
    "CUST001": {"name": "Nguyen Van A", "toi": 150_000_000, "churn_probability": 0.7, "tenure_months": 36},
    "CUST002": {"name": "Tran Thi B",  "toi": 50_000_000,  "churn_probability": 0.3, "tenure_months": 12},
    "CUST003": {"name": "Le Van C",    "toi": 80_000_000,  "churn_probability": 0.5, "tenure_months": 24},
}
```

Logic đánh giá:
- **Churn ≥ 0.6 VÀ TOI ≥ 100M VND** → `increase_credit_limit` (high-risk)
- **Churn ≥ 0.4** → `send_email` (confidence trung bình)
- **Churn < 0.4** → `send_email` (confidence cao)

**Nhận xét:** Sử dụng `random.uniform()` để tạo confidence score thực tế hơn thay vì hardcode một giá trị cố định. Customer không tồn tại trong database sẽ nhận action safe (`send_email`) với confidence thấp.

---

### Bước 3 — Implement Confidence Routing và Hard Rules

Tạo conditional edge function `route_action()` với 3 rules:

| Rule | Điều kiện | Kết quả |
|------|-----------|---------|
| **Rule 1 — Policy Override** | `proposed_action == "increase_credit_limit"` | → `execute_high_risk_action` (bất kể confidence) |
| **Rule 2 — Auto-Execute** | low-risk + `confidence ≥ 0.85` | → `execute_low_risk_action` |
| **Rule 3 — Escalate** | low-risk + `confidence < 0.85` | → `execute_high_risk_action` |

```python
def route_action(state: GraphState) -> str:
    if proposed_action in HIGH_RISK_ACTIONS:    # Rule 1
        return "execute_high_risk_action"
    if confidence_score >= CONFIDENCE_THRESHOLD: # Rule 2
        return "execute_low_risk_action"
    return "execute_high_risk_action"            # Rule 3
```

**Nhận xét:** Thứ tự kiểm tra rất quan trọng — Rule 1 (Policy Override) **phải đứng trước** Rule 2 để đảm bảo hard policy không bao giờ bị confidence score ghi đè. Ví dụ: `increase_credit_limit` với confidence `0.99` vẫn phải qua human review.

---

### Bước 4 — Compile Graph với Interrupts

Compile `StateGraph` với `MemorySaver` (checkpointer) và `interrupt_before`:

```python
memory = MemorySaver()

graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["execute_high_risk_action"],
)
```

**Nhận xét:**
- `MemorySaver` giữ state trong memory, đảm bảo dữ liệu customer không bị mất trong khi chờ human review.
- `interrupt_before` (không phải `interrupt_after`) đảm bảo node `execute_high_risk_action` **chưa được thực thi** khi graph dừng lại → human có quyền reject trước khi action xảy ra.

---

### Bước 5 — Xây dựng Streamlit Approval Interface

Giao diện `app.py` bao gồm:

| Thành phần | Chức năng |
|------------|-----------|
| **Sidebar** | Chọn Customer ID, hiển thị thông tin, nút "Evaluate Customer" |
| **Agent Reasoning Output** | Bảng hiển thị `proposed_action`, `confidence_score`, `reasoning` |
| **Confidence Meter** | `st.metric()` + `st.progress()` hiển thị trực quan |
| **Action Card** | Colour-coded: 🔴 high-risk / 🟢 low-risk / 🟡 low confidence |
| **Human Review Panel** | 3 nút: ✅ Approve · ❌ Reject · ✏️ Edit & Approve |
| **Audit Log Viewer** | `st.dataframe()` hiển thị lịch sử quyết định |

Luồng xử lý khi human nhấn nút:
```
Button click → graph.update_state(config, {"human_decision": decision})
            → graph.invoke(None, config)  # resume
            → st.rerun()  # refresh UI
```

**Nhận xét:** Graph được lưu trong `st.session_state` để tránh tạo lại mỗi lần Streamlit rerun. Mỗi lần evaluate tạo `thread_id` mới để không ảnh hưởng các phiên trước.

---

### Bước 6 — Ghi Audit Log

Hàm `_append_audit_log()` đảm bảo **không ghi đè** dữ liệu cũ:

```python
def _append_audit_log(entry: AuditEntry) -> None:
    # 1. Đọc danh sách hiện có
    logs = json.load(f) if os.path.exists(AUDIT_LOG_PATH) else []
    # 2. Append entry mới
    logs.append(entry.model_dump())
    # 3. Ghi lại toàn bộ danh sách
    json.dump(logs, f, ensure_ascii=False, indent=2)
```

Cả hai node execution đều ghi audit log:
- `execute_low_risk_action` → `reviewer_id = "auto"`, `decision = "auto_approved"`
- `execute_high_risk_action` → `reviewer_id = "operator_01"`, `decision` = approve/reject/edit

---

## 3. Kết quả kiểm tra

### Checklist hoàn thành

| # | Tiêu chí | Trạng thái |
|---|----------|------------|
| 1 | `GraphState` chứa đủ 5 trường (`customer_id`, `proposed_action`, `confidence_score`, `reasoning`, `human_decision`) | ✅ |
| 2 | State tồn tại xuyên suốt workflow, không mất khi interrupt | ✅ |
| 3 | Agent output có `proposed_action`, `confidence_score` (0.0–1.0), `reasoning` | ✅ |
| 4 | **Policy Override:** `increase_credit_limit` luôn → Human Review (kể cả confidence = 0.99) | ✅ |
| 5 | **Auto-Execute:** `send_email` + confidence ≥ 0.85 → tự động thực thi | ✅ |
| 6 | **Escalate:** `send_email` + confidence < 0.85 → Human Review | ✅ |
| 7 | Graph compile với `MemorySaver` + `interrupt_before=["execute_high_risk_action"]` | ✅ |
| 8 | Streamlit hiển thị Action Card + 3 nút (Approve/Reject/Edit) | ✅ |
| 9 | Approve → `update_state` → `invoke(None)` → resume → execute | ✅ |
| 10 | Reject → `update_state` → `invoke(None)` → resume → abort | ✅ |
| 11 | Edit → chỉnh sửa action → `update_state` → resume → execute edited action | ✅ |
| 12 | Audit log ghi nhận mọi quyết định (approve/reject/edit/auto_approved) | ✅ |
| 13 | Audit log **không bị ghi đè** (append-only) | ✅ |

### Test cases

| Test | Customer | Input | Expected | Actual | Kết quả |
|------|----------|-------|----------|--------|---------|
| TC1 | CUST001 | Churn=0.7, TOI=150M | 🔴 `increase_credit_limit` → Interrupt | Interrupt, chờ review | ✅ PASS |
| TC2 | CUST002 | Churn=0.3, TOI=50M | 🟢 `send_email` → Auto-execute (confidence cao) | Auto-execute | ✅ PASS |
| TC3 | CUST003 | Churn=0.5, TOI=80M | 🟡 `send_email` → Tuỳ confidence | Tuỳ confidence score random | ✅ PASS |
| TC4 | CUST_NEW | Không có trong DB | `send_email` → confidence thấp | send_email, confidence 0.6–0.8 | ✅ PASS |
| TC5 | CUST001 | Approve sau interrupt | Ghi audit log, decision=approve | Audit log ghi nhận | ✅ PASS |
| TC6 | CUST001 | Reject sau interrupt | Ghi audit log, decision=reject | Audit log ghi nhận | ✅ PASS |
| TC7 | CUST001 | Edit & Approve | Action được chỉnh sửa, ghi audit | Audit log ghi nhận | ✅ PASS |

---

## 4. Trả lời Reflection Questions

### Câu 1: `interrupt_before` hay `interrupt_after`?

> *Nếu mục tiêu là để con người rewrite một customer retention email trước khi nó di chuyển đến routing node, bạn sẽ dùng `interrupt_before` hay `interrupt_after`?*

**Trả lời:** Sử dụng **`interrupt_after`** node generate email.

**Lý do:** Trong trường hợp này, ta cần email **đã được generate xong** (node đã chạy) để human có thể đọc và chỉnh sửa nội dung. Nếu dùng `interrupt_before`, node generate email chưa chạy → không có email nào để review. Dùng `interrupt_after` giúp:
- Node generate email **chạy xong** → output email nằm trong state
- Graph **dừng sau** node đó → human đọc, chỉnh sửa email trong state
- Sau khi human edit xong → resume graph → email đã chỉnh sửa tiếp tục đến routing node

So sánh:
| Trường hợp | Dùng | Lý do |
|------------|------|-------|
| Review **trước** khi action xảy ra (lab này) | `interrupt_before` | Action chưa thực thi, human có quyền reject |
| Review **sau** khi content được generate | `interrupt_after` | Content đã có, human cần xem và edit |

---

### Câu 2: Giải pháp chống Alert Fatigue

> *Streamlit UI ép human review 500 actions `send_email` mỗi ngày vì confidence bị kẹt ở 0.82, ngay dưới threshold 0.85. Làm sao ngăn Alert Fatigue?*

**Trả lời:** Có thể áp dụng nhiều giải pháp kết hợp:

#### Giải pháp UI/UX:
1. **Batch Approval** — Nhóm các action cùng loại (`send_email`) với confidence tương đương lại, cho phép human approve hàng loạt thay vì từng cái một.
2. **Priority Queue** — Sắp xếp các pending action theo mức độ ưu tiên (confidence thấp nhất lên trước), những action gần threshold có thể xếp cuối.
3. **Auto-dismiss Timer** — Action `send_email` với confidence ≥ 0.80 nếu không bị reject trong 30 phút → tự động approve.

#### Giải pháp Architecture:
4. **Dynamic Threshold** — Thay vì threshold cố định 0.85, sử dụng adaptive threshold dựa trên lịch sử approve rate. Nếu 95% `send_email` với confidence 0.82 đều được approve → hạ threshold xuống 0.80 cho action type này.
5. **Action-specific Threshold** — Phân biệt threshold theo loại action:
   - `send_email`: threshold = 0.75 (low-risk, hậu quả nhỏ)
   - `increase_credit_limit`: luôn human review (hard policy)
6. **Feedback Loop** — Thu thập kết quả thực tế của các action đã execute, dùng để recalibrate confidence model → giảm số lượng false escalation.

---

### Câu 3: Nguy hiểm của việc phụ thuộc vào self-reported confidence

> *Agent thường báo confidence 0.95 cho `increase_credit_limit` nhưng lại thường sai về thu nhập thực tế. Tại sao nguy hiểm? Cách calibrate?*

**Trả lời:**

#### Tại sao nguy hiểm:
- **LLM không biết nó sai** — Confidence score do LLM tự đánh giá chỉ phản ánh "mức độ chắc chắn chủ quan" chứ không phải "xác suất đúng thực tế". LLM có thể rất tự tin (0.95) nhưng dựa trên thông tin sai hoặc hallucination.
- **Miscalibration** — Nghiên cứu cho thấy LLM thường bị overconfident: báo 0.95 nhưng tỉ lệ đúng thực tế chỉ 0.70. Nếu hệ thống tin tưởng confidence này để routing, các action sai sẽ bị auto-execute.
- **Gaming the system** — Nếu LLM "học" được rằng confidence cao = bypass review, nó có động lực (trong adversarial setting) để luôn báo confidence cao.

#### Cách calibrate:
1. **External Validation** — Thêm bước verify thông tin factual (thu nhập khách hàng) bằng cách query database thực tế **trước** khi routing, so sánh với những gì LLM claim.
2. **Historical Calibration** — Thu thập dữ liệu: "confidence = X → kết quả đúng/sai bao nhiêu %", xây dựng calibration curve, điều chỉnh confidence trước routing: `calibrated_score = calibration_function(raw_score)`.
3. **Ensemble Confidence** — Không chỉ dùng 1 LLM đánh giá, mà chạy nhiều model hoặc nhiều lần, lấy trung bình/phương sai. Nếu phương sai cao → confidence thực tế thấp hơn.
4. **Hard Policy Override** — Như đã implement trong lab: bất kể confidence, `increase_credit_limit` **luôn** phải qua human review. Đây chính là "safety net" cho trường hợp LLM overconfident.

---

## 5. Kiến thức thu được

### Về LangGraph
- **StateGraph** cho phép xây dựng workflow có state xuyên suốt, thích hợp cho các bài toán cần tạm dừng/resume.
- **`interrupt_before`** là cơ chế core của HITL — graph dừng trước node nguy hiểm, giữ state trong checkpointer.
- **`MemorySaver`** đóng vai trò checkpointer, đảm bảo state không bị mất khi graph tạm dừng.
- **`update_state()` + `invoke(None)`** là pattern chuẩn để resume graph sau human decision.

### Về HITL Architecture
- **Policy Override > Confidence** — Hard rule luôn ưu tiên hơn confidence score vì confidence có thể bị miscalibrate.
- **Audit Trail là bắt buộc** — Mọi quyết định (dù auto hay manual) đều phải được ghi log để truy vết.
- **Alert Fatigue là real** — Threshold cần được thiết kế cẩn thận, nếu không operator sẽ "approve mọi thứ" vì quá mệt mỏi.

### Về Streamlit
- `st.session_state` giúp lưu trạng thái giữa các lần rerun.
- `st.rerun()` trigger refresh UI sau khi state thay đổi.
- Layout với `st.columns()`, `st.sidebar`, `st.metric()` tạo dashboard trực quan.

---

## 6. Kết luận

Lab 27 đã giúp em hiểu rõ cách xây dựng một hệ thống HITL hoàn chỉnh từ workflow engine (LangGraph) đến giao diện (Streamlit). Điểm quan trọng nhất em rút ra là: **trong các hệ thống AI thực tế, không phải lúc nào cũng nên tin tưởng hoàn toàn vào quyết định của AI** — cần có cơ chế hard policy, human review, và audit trail để đảm bảo an toàn và khả năng truy vết.

---

<p align="center">
  <strong>Nguyễn Đình Duy</strong> — 2A202601046<br>
  AI thực chiến — Track 3, Day 27
</p>
