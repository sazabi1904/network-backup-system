# Bản ghép TV2 TV5 theo danh sách đầu việc ngày 18/11/2026

> Cập nhật tiếp theo: xem [OSPF TV2–TV5](OSPF_TV2_TV5.md). Các giới hạn OSPF dưới đây mô tả bản tích hợp đầu ngày, trước khi bổ sung scope OSPF.

## Kết quả và nền mã

Đã lấy `main` mới nhất tại thời điểm fetch: `f731265` (merge PR #10), tiếp nhận bản TV2 cục bộ `c6929ad`, rồi sửa trên nhánh riêng `integration/tv2-tv5-20261118`. Tài liệu đầu vào: Danh_sach_dau_viec_TV2_TV5.docx. Hai ảnh là nhận định cần kiểm chứng, không được dùng thay kết quả chạy.

Trước sửa: **4 failed, 113 passed**, lỗi Deploy gọi `verify_commands_present` không tồn tại. Đọc mã cũng xác nhận Restore đang dùng phép kiểm tra tập con, không bắt buộc khớp cấu hình đầy đủ; phần mô tả trong verification.py nói RestoreManager có kiểm tra bổ sung nhưng thực tế không có.

Sau sửa: **136 passed**. Đã thử R1 và R3 trước, sau đó mở rộng bốn router GNS3 qua SSH. Cả bốn đạt deploy, read-back, restore và bài cố ý làm verifier thất bại để kiểm tra rollback. Đã xác minh cấu hình sau cùng khớp baseline. Đây là router ảo chạy hệ điều hành thực, không phải FakeDevice hoặc thiết bị phần cứng.

Phạm vi: **identity MikroTik / description interface có sẵn trên FRR**. Không coi đây là restore toàn bộ router hoặc OSPF.

## Đối chiếu yêu cầu

| Mã | Kết quả trong bản ghép |
| --- | --- |
| TV2-01 | Có WriteSSHAdapter opt-in; mặc định vẫn chỉ đọc. Ghi và restore đã kiểm chứng trong phạm vi nêu trên. |
| TV2-02 | Giữ strict host key, credential_ref, timeout, allowlist đọc; kiểm tra lệnh ghi, không trả raw config nhạy cảm trong kết quả xác minh của adapter thật. |
| TV2-03 | RouterOS 7.23.8: xử lý prompt trước export và sau đổi tên; canonical hóa timestamp chỉ cho so sánh. Thử ghi/read-back/restore đạt. Không reset router. |
| TV2-04 | FRR 8.2.2: Linux shell → vtysh với ngữ cảnh configure/interface/exit; description tồn tại qua lần gọi vtysh khác, restore cả trường hợp trước đó không có description. **Chưa làm reload/startup persistence/reboot.** |
| TV2-05 | Thêm DeviceWriteError với code WRITE_TIMEOUT, WRITE_CONNECTION_LOST, WRITE_TRANSPORT_ERROR, WRITE_PERMISSION_DENIED, WRITE_REJECTED, WRITE_INVALID_RESPONSE và may_have_applied; không đưa output lỗi/secret vào exception. Lỗi đọc/kết nối giữ hợp đồng cũ. |
| TV2-06 | register_device_adapters(write=True) đăng ký WriteSSHAdapter qua Factory; mặc định/subclass cũ giữ read-only. CLI phục hồi registry trong finally; test hồi quy hiện có đạt. |
| TV5-01 | Khôi phục verify_commands_present; Deploy demo không còn AttributeError. |
| TV5-02 | verify_config_match yêu cầu khớp canonical đầy đủ, giữ thứ tự, lặp và thụt dòng; báo thiếu/thừa/sai. Restore không cho verifier tùy biến nới lỏng thành subset check. |
| TV5-03 | Deploy gọi verifier theo nền tảng của TV2; restore chuẩn hóa theo adapter mà không sửa hash/content gốc của snapshot TV4. |
| TV5-04 | Giữ backup thành công, đúng snapshot_id/hash trước deploy; thêm preflight trước backup/ghi, phân biệt trạng thái partial apply, xác minh rollback bằng luồng restore nghiêm ngặt. |
| TV5-05 | **Chưa đạt OSPF thật**. Chế độ ghi từ chối các template OSPF hiện tại. Xem các vấn đề bên dưới. |
| TV5-06 | Restore thật qua CLI cần snapshot_id cụ thể; tạo và xác thực backup dự phòng trước restore. Backup này có recovery_snapshot_id trong kết quả thành công. |
| PH-01 | API NetworkDevice không đổi; mở rộng capability/preflight/verification và error metadata theo kiểu tùy chọn. |
| PH-02 | Chốt phạm vi identity/description cho vòng tích hợp này. **Chưa chốt phạm vi OSPF/delta routing.** |
| PH-03 | Dry-run → xác nhận → backup → ghi → verify → restore/rollback. Có khóa theo host/port trong cùng tiến trình Python, bao trùm thao tác và cho phép rollback lồng. **Chưa khóa giữa nhiều process/máy chạy độc lập.** |
| PH-04 | Dùng snapshot_id chính xác; thử partial-apply timeout bằng test, rollback thật bằng lỗi verifier có chủ đích. **Chưa diễn tập mất SSH thật/console recovery.** |
| PH-05 | cli.py có --write-scope managed, --known-hosts, --confirm-write, --snapshot-id; main.py TV5 có mục 5/6 chọn deploy/restore thật. |
| PH-06 | Có runner dùng chung, test và JSON bằng chứng; cần nhóm review trước merge main. |

## Tệp thay đổi chính

- devices/ssh_adapter.py, devices/write_adapter.py: Factory opt-in, xuất cấu hình sạch, phân loại lỗi ghi, giữ ngữ cảnh cấu hình.
- core/exceptions.py, core/operation_lock.py: hợp đồng lỗi và khóa thao tác theo endpoint trong một tiến trình.
- services/verification.py, services/config_manager.py, services/restore.py: sửa các lỗi giao tiếp TV5, preflight, backup trước restore, kiểm tra khớp đầy đủ, khóa thao tác.
- cli.py, main.py: nối chế độ ghi vào luồng chung, chọn thiết bị/snapshot/xác nhận rõ ràng.
- TV2/ssh/acceptance.py: runner kiểm thử dùng lại được, không hard-code tài khoản hoặc đường dẫn cá nhân.
- tests/test_tv2_tv5_contract_20261118.py: kiểm thử thiếu/thừa/ngữ cảnh, snapshot sai, preflight, backup lỗi, rollback/lock, lỗi ghi đã che secret và hủy thao tác trong menu.

Không thay đổi service TV4, Collector TV3, inventory chung, mật khẩu hoặc IP quản trị. Test tự động mô phỏng lỗi timeout sau áp dụng; bài SSH thật chủ động gây lỗi xác minh, không cố cắt đường quản trị.

## Cách TV5 kiểm thử

Từ thư mục gốc bản ghép, cấu hình inventory cục bộ và biến môi trường theo credential_ref; xác minh host keys trước. Không đưa credentials lên Git.

```sh
python -m pytest -q
python main.py
```

Trong menu TV5: mục 5 là deploy, có dry-run trước xác nhận `GHI`; mục 6 là restore theo snapshot ID. Template thật chỉ dùng `tv2_identity` hoặc `tv2_description`. Credentials lấy qua cơ chế environment hiện có; menu không yêu cầu nhập secret vào thông tin báo cáo.

Chạy nghiệm thu một MikroTik và một FRR trước:

```sh
python -m TV2.ssh.acceptance --inventory inventory.local.yaml --device MikroTik-R1 --device FRR-R3 --known-hosts known_hosts.lab --confirm-write
python -m TV2.ssh.acceptance --inventory inventory.local.yaml --device MikroTik-R1 --device FRR-R3 --known-hosts known_hosts.lab --confirm-write --rollback-check
```

FRR mặc định thử description của eth0; dùng --interface nếu lab dùng tên khác. Runner tạo backup, thay đổi có giới hạn, đọc lại, restore trong finally nếu cần và lưu báo cáo có thời điểm riêng trong reports/tv2-acceptance. Các dòng lỗi verifier trong bài --rollback-check là lỗi được tạo có chủ đích; chỉ PASS nếu rollback được xác minh.

Trên máy hiện tại dùng interpreter `../.venv/bin/python`; inventory và known_hosts ở `../validation-20261117`. Gateway localhost và GNS3 phải đang chạy. Gateway không tự khởi động sau reboot; SSH timeout do gateway dừng không đồng nghĩa TV5 lỗi.

## OSPF và các mốc chưa đạt

Template MikroTik hiện dùng /routing ospf network và giả định instance default; cần chuyển thiết kế sang RouterOS 7 với interface-template, instance/area có tên rõ ràng, router ID riêng và thao tác không tạo trùng. Tài liệu hãng: https://manual.mikrotik.com/docs/getting-started/upgrading-to-v7/ .

Template FRR có write memory nằm trong danh sách gửi lệnh trước xác minh. Cần tách bước lưu startup khỏi deploy và chỉ thực hiện sau xác minh, với backup/recovery cho startup. Không bật rộng allowlist để template này chạy khi chưa có cơ chế restore routing tương ứng.

Còn cần thiết kế delta thêm/sửa/xóa đối tượng OSPF, quản lý persistence, khóa liên tiến trình và phương án console recovery. Không đánh dấu các mục này PASS chỉ vì identity/description đã chạy được.

## Bằng chứng ngày 18/11

Xem `TV2/evidence/20261118/restore.json`, `rollback.json` và `pytest.txt`. Mỗi record có router, scope, baseline_id, snapshot_id/recovery_snapshot_id, kết quả deploy/restore, exact_hash_match. Không chứa mật khẩu hoặc nội dung export cấu hình.

Báo cáo này thay thế trạng thái trong GHI_VA_RESTORE.md ngày 17/11 về điểm nối TV5. Bản sửa ở nhánh tích hợp cục bộ; không suy ra đã được merge hoặc công bố đầy đủ trên GitHub.
