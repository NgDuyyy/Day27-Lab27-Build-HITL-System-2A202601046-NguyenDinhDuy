```markdown
# 5. Kiểm tra kết quả

Nêu cách tự kiểm tra và các lỗi thường gặp trong quá trình triển khai hệ thống HITL.

---

## I. Checklist kiểm tra chức năng

### 1. Kiểm tra State
Đảm bảo `GraphState` chứa đầy đủ các trường dữ liệu:
```text
customer_id
proposed_action
confidence_score
reasoning
human_decision

```

Checklist xác thực:

* [ ] State tồn tại xuyên suốt workflow của graph.
* [ ] State không bị mất khi graph rơi vào trạng thái interrupt.
* [ ] `human_decision` có thể được cập nhật chính xác từ giao diện Streamlit.

---

### 2. Kiểm tra Agent Reasoning

Chạy thử nghiệm với một customer input cụ thể và kiểm tra output của Agent:

* [ ] Output có `proposed_action`.
* [ ] Output có `confidence_score`.
* [ ] Output có `reasoning`.
* [ ] Giá trị điểm tin cậy thỏa mãn: `0.0 <= confidence_score <= 1.0`.

---

### 3. Kiểm tra Hard Rule (Policy Override)

Test case:

```python
proposed_action = "increase_credit_limit"
confidence_score = 0.99

```

* **Kết quả bắt buộc:** `Human Review`
* **Nghiêm cấm:** `Auto Execute` (bất kể điểm confidence cao đến mức nào).

---

### 4. Kiểm tra Auto-Execute (Low-Risk & High Confidence)

Test case:

```python
proposed_action = "send_email"
confidence_score = 0.90

```

* **Kết quả mong đợi:** Route trực tiếp đến node `execute_low_risk_action`.

---

### 5. Kiểm tra Escalation (Low-Risk nhưng Low Confidence)

Test case:

```python
proposed_action = "send_email"
confidence_score = 0.82

```

* **Kết quả mong đợi:** `Human Review` (do confidence thấp hơn ngưỡng `0.85`).

---

### 6. Kiểm tra Cơ chế Interrupt

Đảm bảo graph được biên dịch chính xác với checkpointer và breakpoint:

```python
graph = builder.compile(
    checkpointer=memory,
    interrupt_before=["execute_high_risk_action"]
)

```

Khi luồng đi tới high-risk action, kiểm tra:

* [ ] Node `execute_high_risk_action` **chưa** được thực thi.
* [ ] Graph dừng lại ở trạng thái `pending`.
* [ ] Toàn bộ dữ liệu của customer trong `state` vẫn được bảo toàn nguyên vẹn.

---

### 7. Kiểm tra Giao diện Streamlit UI

Giao diện Streamlit phải hiển thị đầy đủ:

* [ ] Thẻ thông tin Action Card: `proposed_action`, `confidence_score`, `reasoning`.
* [ ] 3 nút tương tác: **Approve**, **Reject**, **Edit**.

#### Luồng tương tác của các Button:

* **Test Approve:**

```text
Approve ──> update_state ──> resume graph ──> execute action

```

* **Test Reject:**

```text
Reject ──> update_state ──> resume graph ──> abort action

```

* **Test Edit:**

```text
Edit (sửa payload) ──> update_state ──> resume graph ──> execute edited action

```

---

### 8. Kiểm tra Audit Log

Sau mỗi quyết định của con người (`human_decision`), hệ thống phải ghi nhận một entry mới vào `audit_log.json`.

Cấu trúc mỗi entry bắt buộc gồm:

```json
{
  "timestamp": "...",
  "agent_id": "...",
  "action": "...",
  "confidence": 0.0,
  "reviewer_id": "...",
  "decision": "..."
}

```

Checklist log:

* [ ] Quyết định **Approve** được ghi nhận.
* [ ] Quyết định **Reject** được ghi nhận.
* [ ] Quyết định **Edit** được ghi nhận.
* [ ] **Không ghi đè (overwrite)** làm mất dữ liệu audit cũ trong file.

---

## II. Các lỗi thường gặp (Common Pitfalls)

### 1. Graph mất state sau khi interrupt

* **Nguyên nhân:** Chưa cấu hình bộ nhớ lưu trữ phiên làm việc (Checkpointer).
* **Cách khắc phục:** Đảm bảo đã import và truyền checkpointer vào lệnh compile:
```python
from langgraph.checkpoint.memory import MemorySaver
memory = MemorySaver()
graph = builder.compile(checkpointer=memory, ...)

```



---

### 2. High-risk action tự chạy trước khi human kịp review

* **Nguyên nhân:** Đặt interrupt sai vị trí hoặc dùng sai directive.
* **Cách khắc phục:** Phải sử dụng:
```python
interrupt_before=["execute_high_risk_action"]

```


*(Tuyệt đối không dùng `interrupt_after` vì action sẽ bị thực hiện trước khi dừng graph).*

---

### 3. Hard rule bị Confidence score ghi đè (Override)

* **Sai lầm phổ biến:**
```text
confidence = 0.99 ──> Auto execute "increase_credit_limit" (SAI)

```


* **Quy tắc chuẩn:**
```text
increase_credit_limit ──> Luôn luôn bắt buộc Human Review (ĐÚNG)

```


* **Lưu ý:** Trong hàm `route_action`, logic kiểm tra **Hard Policy Rule** phải luôn được đặt lên hàng đầu trước khi xét tới ngưỡng `confidence_score`.

---

### 4. Nhấn nút trên Streamlit nhưng Graph không chạy tiếp

* **Cách khắc phục:** Cần thực hiện đầy đủ 2 bước tuần tự:
1. Cập nhật state với quyết định của con người:
```python
graph.update_state(config, {"human_decision": decision})

```


2. Kích hoạt tiếp tục phiên chạy:
```python
graph.invoke(None, config)

```





---

### 5. Không lấy được Pending State

* **Cách khắc phục:** Sử dụng hàm:
```python
state_snapshot = graph.get_state(config)

```


* **Lưu ý:** Tham số `config` (chứa `configurable: {"thread_id": "..."}`) phải trùng khớp hoàn toàn với `thread_id` của lần `invoke` trước đó.

---

### 6. File Audit Log bị ghi đè dữ liệu

* **Sai lầm:** Ghi đè file bằng một object JSON duy nhất, xóa sạch lịch sử trước đó.
* **Quy trình chuẩn:**
1. Đọc danh sách các audit entry hiện có từ file.
2. Parse thành list các object.
3. `append` đối tượng `AuditEntry` mới vào danh sách.
4. Ghi ngược lại toàn bộ danh sách vào file `audit_log.json`.


* **Khuyến nghị Production:** Chuyển sang sử dụng cơ sở dữ liệu chuyên dụng dạng append-only (như PostgreSQL append-only table) để đảm bảo toàn vẹn dữ liệu kiểm toán.

```

```