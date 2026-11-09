# Thành viên 3 – Inventory, kiểm tra khả dụng và thu thập thông tin

**Đề tài:** Hệ thống sao lưu và khôi phục cấu hình tập trung  
**Ngày cập nhật:** 09/11/2026

## Phạm vi nhiệm vụ

Thành viên 3 phụ trách:

- Đọc và quản lý Inventory thiết bị.
- Thêm, sửa, xóa và lọc thiết bị.
- Kết nối đồng thời nhiều thiết bị.
- Phân loại trạng thái online, offline, timeout và lỗi xác thực.
- Thu thập và chuẩn hóa thông tin MikroTik/FRR.
- Xuất kết quả ra JSON và CSV.
- Cung cấp dữ liệu interface, route và OSPF cho thành viên 5 xác minh.

## Sản phẩm

| File | Chức năng |
|---|---|
| `services/inventory.py` | Quản lý Inventory YAML/JSON |
| `services/connection_manager.py` | Kết nối đồng thời và cô lập lỗi từng thiết bị |
| `services/collector.py` | Thu thập, chuẩn hóa và xuất báo cáo |
| `data/inventory.yaml` | Danh sách 4 router mẫu |
| `tests/test_inventory.py` | Kiểm thử Inventory |
| `tests/test_connection_manager.py` | Kiểm thử kết nối đồng thời |
| `tests/test_collector.py` | Kiểm thử thu thập và xuất báo cáo |

## Inventory

Lớp `InventoryManager` hỗ trợ:

- `load()`: đọc YAML hoặc JSON.
- `list_devices()`: lọc theo group, role và tag.
- `add_device()`: thêm thiết bị.
- `update_device()`: cập nhật thuộc tính thiết bị.
- `remove_device()`: xóa thiết bị.
- `save()`: lưu Inventory an toàn.
- Kiểm tra port hợp lệ từ `1` đến `65535`.

## Kết nối đồng thời

Lớp `ConnectionManager` sử dụng `ThreadPoolExecutor` để xử lý nhiều router.

Mỗi thiết bị được:

1. Tạo adapter riêng.
2. Kết nối độc lập.
3. Thực hiện tác vụ.
4. Ngắt kết nối trong `finally`.
5. Ghi nhận kết quả và mã lỗi riêng.

Một router offline hoặc timeout không làm dừng các router còn lại.

## Thu thập thông tin

Lớp `Collector` thu thập các mục:

- Thông tin hệ điều hành, phiên bản và uptime.
- CPU và RAM.
- Serial thiết bị.
- Interface.
- Bảng định tuyến.
- ARP.
- MAC table.
- CDP/LLDP hoặc thông tin láng giềng.
- OSPF.

Dữ liệu được chuẩn hóa riêng cho:

- MikroTik RouterOS.
- FRRouting.

Thuộc tính hoặc lệnh không được nền tảng hỗ trợ sẽ được đánh dấu `unsupported`, không làm dừng toàn bộ lần thu thập.

## Xuất báo cáo

Collector hỗ trợ:

- `export_json()`: xuất báo cáo JSON có cấu trúc.
- `export_csv()`: xuất một dòng cho mỗi thiết bị.
- Loại bỏ output thô và tham chiếu xác thực khỏi báo cáo.
- `get_verification_data()`: cung cấp bản sao an toàn của interface, route và OSPF cho TV5.


## Kiểm thử

Chạy toàn bộ test:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Kết quả ngày 09/11/2026:

```text
34 passed in 1.38s
```

Bộ test bao gồm trường hợp quản lý 4 router đồng thời và xác nhận một router offline không làm dừng ba router còn lại.

## Giới hạn hiện tại

Các chức năng đã được kiểm thử bằng `FakeDevice` và adapter mô phỏng.

Việc kiểm thử SSH trực tiếp trên GNS3 vẫn phụ thuộc vào:

- Topology và trạng thái lab của TV2.
- Adapter MikroTik/FRR thực tế của TV2.
- Địa chỉ IP và thông tin xác thực của môi trường lab.

Không lưu mật khẩu, file `.env`, log vận hành hoặc output thô chứa dữ liệu nhạy cảm vào Git.