# Issue Analysis — bản bàn giao và đề xuất chốt nhóm

Trạng thái: triển khai QR ở mức mô phỏng; chưa có phê duyệt OD-01/02/03/08.
Đối chiếu dưới đây dựa trên README, contracts và decisions đã dẫn A1 trong repo;
chưa kiểm tra trực tiếp hai PDF, nên cần rà lại FR/NFR và số mục trước khi nộp.
Hai issue A2 được xác định theo README §4, chưa đối chiếu nguyên văn đề M2.

## Đối chiếu A1 → A2

| Yêu cầu/nguồn baseline | Issue A2 | Xử lý / bằng chứng cần có |
|---|---|---|
| FR validateQR, evaluateAccess, unlockGate (Table 16) | QR tĩnh dễ sao chép | Chữ ký đúng mới trả credential; quyền truy cập vẫn do policy quyết định |
| FR ghi nhận qua cổng (§3.5.3, §5.3.2) | Mất mạng giữa giao dịch | ACK không đồng nghĩa passage; chỉ ghi attendance theo quy tắc nhóm chốt |
| FR đồng bộ (§3.5.5, Table 31) | Mất kết nối | Outbox và resend cùng transaction_id; Hub idempotent |
| NFR bảo mật (ADR-002, §3.5.4) | QR giả/hết hạn/replay | Kiểm chữ ký, audience, exp, iat, jti; Edge chỉ có public key |
| NFR sẵn sàng offline (Table 28) | Mất kết nối | Cache ≤5 phút fresh; offline ≤2 giờ stale có đánh dấu; quá hạn deny |
| NFR độ bền dữ liệu (Table 32, ADR-003) | Mất kết nối khi ghi/sync | Persist attempt trước unlock; attendance + outbox atomic; lỗi ghi fail closed |
| NFR thời gian (Table 29, §4.2.3) | Cả hai | Gate timeout 800 ms, passage 15 s; cần đo integration, unit QR chưa chứng minh |

## Kịch bản và tiêu chí kiểm chứng

| ID | Điều kiện/kích hoạt | Kết quả và phép kiểm |
|---|---|---|
| NET-01 | Ngắt Hub trước scan; QR hợp lệ, cache fresh | Quyết định tại Edge; chỉ unlock sau persist attempt; sau passage có record + outbox PENDING |
| NET-02 | Offline với cache ở 5 phút, 2 giờ và >2 giờ | Theo Table 28; stale flag khi dùng dữ liệu cũ, quá 2 giờ deny và không gọi gate |
| NET-03 | Hub commit nhưng ACK bị mất | Giữ PENDING; gửi lại cùng transaction_id; Hub chỉ có một record, ACK mới chuyển SYNCED |
| NET-04 | Lỗi lưu attempt trước unlock / crash giữa record-outbox | Không unlock khi lưu attempt lỗi; atomic rollback không để record đơn lẻ |
| QR-01 | Token ký đúng, now trong [iat,exp) | VALID, credential đúng; không suy ra ALLOW hay attendance |
| QR-02 | Scan tại exp và sau exp | EXPIRED, credential None; không gọi gate khi tích hợp |
| QR-03 | Scan token lần hai, gồm scan đồng thời | Một VALID duy nhất trong cùng guard; còn lại REPLAYED |
| QR-04 | Sửa signature / sai audience / kid không biết / malformed | Reject tương ứng; input bị từ chối không tiêu thụ jti |
| QR-05 | Replay store hỏng / clock naive hoặc trước iat | StorageError / CLOCK_UNRELIABLE; fail closed |

QR unit tests đã viết trong tests/unit/qr/test_qr_scenarios_pending.py (tên cũ được giữ).
NET-* và khẳng định không gọi gate là tiêu chí integration cần Kim/Nhật thực hiện;
không được báo là đã pass chỉ từ unit tests validator.

## Đề xuất luồng cấp/ký QR để chốt

Hub xác thực nhân viên → cấp token ngắn hạn với jti duy nhất → ký bằng private key
trong Hub → điện thoại nhận và hiển thị → Edge kiểm bằng public key cache.
Mất mạng Edge–Hub vẫn verify token còn hạn; điện thoại không lấy được token mới thì
không tự ký hoặc kéo dài exp; chuyển quy trình hỗ trợ bảo vệ cần nhóm định nghĩa.
Hieu/Khai/Viet cần xác nhận OD-01/02/03; Nhật xác nhận OD-08 về persistence/multi-scanner;
Kim xác nhận reject không gọi gate. Đây là nội dung phối hợp bàn giao, chưa gửi hay được nhóm chấp thuận.

Profile mô phỏng: base64url(JSON).base64url(signature), Ed25519 ký ASCII của phần body;
claims sub,jti,kid,aud (chuỗi), iat,exp (epoch UTC integer); không JWT/JWS, không hỗ trợ
thuật toán do token tự chọn. Thời hạn ví dụ 60 giây, không cố định production;
clock skew bằng 0. Registry public key tiêm qua constructor; không có key thì UNKNOWN_KEY.
Không có key loader/rotation/revocation distribution, issuer policy hay trusted clock health.
Không có signer ở Edge; test tạo key tạm trong RAM, không lưu private key.

Replay chỉ atomic trong một instance/process bằng lock, giữ jti đến exp. Restart hoặc
scanner dùng guard khác có thể chấp nhận lại; chưa đảm bảo replay toàn hệ thống.
Token bị tiêu thụ ngay sau QR verification, dù policy sau đó deny: muốn thử lại phải
lấy token mới. Cần thống nhất semantics trước integration. Registry phải loại public key
đã thu hồi; thời gian phát tán thu hồi offline chưa được giải quyết.

Không sửa interface shared hoặc composition root. Default validator chưa cấu hình luôn
từ chối; /scan và toàn bộ offline flow vẫn scaffold. Không thể coi đây là demo end-to-end.

## Kết quả kiểm chứng môi trường

Ngày 08/11/2026: đã khôi phục Python 3.12.10 và tạo .venv với dependencies dự án.
Chạy pytest: 55 passed, 6 skipped; riêng QR: 18 passed. Sáu test skipped thuộc
access/offline chưa triển khai; không tính là thành công. Có một cảnh báo deprecation
của Starlette TestClient/httpx. Đã sửa import và format của ba file QR sau lần kiểm tra đầu.
Lệnh chạy tests: .venv/Scripts/python.exe -m pytest.
Nguyên nhân ban đầu: python trỏ alias Microsoft Store, py đăng ký đường dẫn Python312
không còn file thực thi; không phải lỗi dependencies hay logic QR.

Validation đầy đủ: scripts/validate.ps1 đã pass (lint, format, workflow, secret scan,
tests: 55 passed, 6 skipped), dùng PATH của .venv/Scripts trong phiên chạy.
