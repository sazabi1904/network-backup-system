# TV3 — Sao lưu cấu hình và quản lý phiên bản

## File bàn giao
- services/backup_manager.py
- services/backup_scheduler.py
- tests/test_backup.py

## Cách sử dụng
Chạy chương trình từ thư mục gốc repository.

- backup(device): thiết bị cần được kết nối trước.
- backup_many(devices, group=None): backup danh sách thiết bị đã kết nối;
  truyền group để lọc nhóm.
- backup_with_connection(device): tự kết nối, backup và ngắt kết nối.
- read_snapshot(snapshot_id): đọc và kiểm tra một phiên bản.
- list_snapshots(device_name): liệt kê phiên bản mới nhất trước.
- search_snapshots(device_name, keyword): tìm theo mã hoặc thời gian.

## Lưu trữ
- Mỗi phiên bản gồm file TXT cấu hình và JSON thông tin phiên bản.
- snapshot_id là tên file bỏ phần đuôi.
- Thời gian lưu theo UTC; SHA-256 dùng để kiểm tra nội dung.
- Lịch sử yêu cầu cặp TXT/JSON hợp lệ.
- backups/ và logs/ được Git bỏ qua.

## Backup theo lịch
- Truyền một hàm không tham số vào BackupScheduler.
- Hàm đó gọi backup_with_connection cho từng thiết bị được chọn.
- interval_seconds=300 tương ứng chờ 5 phút giữa các đợt.
- run() chạy ngay lần đầu, rồi chờ sau khi mỗi đợt kết thúc.
- stop() dừng các đợt tiếp theo; đợt đang chạy được tiếp tục.
- Tiến trình phải đang chạy để duy trì lịch.

## Kiểm thử và tích hợp
- pytest: 8 passed, gồm 7 bài core và 1 bài kiểm tra tính toàn vẹn backup.
- Đã thử thủ công bằng FakeDevice: đơn/nhóm/toàn bộ, offline,
  backup định kỳ, liệt kê, tìm kiếm và đọc lại phiên bản.
- Chưa kiểm thử SSH/GNS3 thật; cần adapter của TV2.
- Lỗi ghi nhật ký có thể truyền ra ngoài; nơi gọi cần xử lý.
- TV1 cần đồng bộ phân công trong README/API_CONTRACTS.
- Phần diff thuộc TV4; BackupManager hiện không cung cấp diff().