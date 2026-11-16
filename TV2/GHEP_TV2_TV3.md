# Ghép mã TV2 và TV3

Cập nhật ngày 16/11/2026, trên nền `main` tại commit `e6b198631907975fb4249ace8e47a56f6917638a`.

Luồng tích hợp đọc Inventory của TV3, tạo adapter TV2 qua Factory, mở SSH, thu thập các mục và xuất báo cáo. TV2 cung cấp kết nối và thực thi lệnh. TV3 quản lý nhiều thiết bị, chuẩn hóa dữ liệu và tổng hợp kết quả.

## Những phần đã sửa và thêm

| File | Thay đổi | Mục đích |
|---|---|---|
| `core/commands.py` | Thêm bảng `COLLECTION_COMMANDS` cho MikroTik và FRR | Adapter và Collector cùng dùng một danh sách lệnh |
| `devices/ssh_adapter.py` | Hỗ trợ các lệnh thu thập trong bảng chung | Cho TV3 đọc serial, interface, route, ARP, MAC, láng giềng và OSPF tùy nền tảng |
| `devices/ssh_adapter.py` | Cho phép bảng RouterOS rỗng, phân loại lệnh thiết bị không hỗ trợ và giữ phiên khi một lệnh thu thập bị từ chối | Collector tiếp tục thu thập các mục còn lại và ghi trạng thái từng mục |
| `devices/ssh_adapter.py` | FRR auto chỉ thử lệnh trực tiếp khi lỗi chỉ rõ lệnh `vtysh` không được CLI nhận diện | Tránh đổi cách gọi khi một lệnh `show` của FRR không được hỗ trợ |
| `devices/ssh_adapter.py` | Factory nhận tùy chọn timeout, known_hosts và frr_shell | CLI truyền cấu hình kết nối đến từng adapter |
| `services/collector.py` | `Collector.COMMANDS` dùng bảng chung | Giữ API Collector hiện có và đồng bộ lệnh với TV2 |
| `main.py` | Thêm `--check-connections`, `--collect`, Inventory, bộ lọc, tùy chọn SSH và thư mục báo cáo | Có điểm chạy tích hợp từ CLI |
| `tests/test_tv2_tv3_integration.py` | Thêm kiểm thử đi qua Inventory, Factory, adapter, ConnectionManager, Collector và CLI | Bắt lỗi ở ranh giới giữa hai thành viên |
| `TV2/ssh/test_ssh_client.py` | Chạy test service với mã đã ghép trong checkout hiện tại | Hai test TV3/TV4 chạy tự động cùng bộ test |
| `README.md`, `TV2/README.md`, `TV3/README.md`, `TV2/ssh/HUONG_DAN_SSH.md` | Cập nhật trạng thái và hướng dẫn chạy | Người trong nhóm có thể tái hiện luồng tích hợp |

## Luồng gọi

```text
main.py --collect --inventory <file>
  InventoryManager.load() và list_devices()
  register_device_adapters(...)
  ConnectionManager.run(infos, operation=Collector().collect)
    DeviceFactory.create(info)
    SSHAdapter.connect()
    Collector.collect(device)
      SSHAdapter.send_command(command)
      chuẩn hóa output thành sections và TaskResult
    SSHAdapter.disconnect()
  Collector.export_json() và export_csv()
```

Mỗi router có đối tượng adapter và phiên SSH riêng. ConnectionManager điều phối các router bằng ThreadPoolExecutor và giữ thứ tự kết quả theo Inventory.

## Chuẩn bị và chạy

Dùng Python 3.10 trở lên từ thư mục gốc repository.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r TV2/ssh/requirements.txt
```

Trên Windows, dùng `.venv\Scripts\python.exe` thay `.venv/bin/python`.

Tạo bản Inventory cục bộ, điền IP quản trị truy cập được từ máy chạy Python. File `data/inventory.yaml` trong repo sử dụng IP minh họa `192.0.2.x`. Các địa chỉ bên dưới lấy từ tài liệu bàn giao SSH và cần đối chiếu với lab đang chạy.

```yaml
- name: MT-R1
  host: 192.168.10.21
  platform: mikrotik
  port: 22
  group: lab
  role: router
  tags: [core]
  credential_ref: lab
- name: FRR-1
  host: 192.168.10.25
  platform: frr
  port: 22
  group: lab
  role: router
  tags: [edge]
  credential_ref: frr
```

Adapter lấy tài khoản từ biến môi trường hoặc `.env` cục bộ theo `credential_ref`. Ví dụ `lab` dùng `LAB_USERNAME` và `LAB_PASSWORD`, `frr` dùng `FRR_USERNAME` và `FRR_PASSWORD`. Mỗi tài khoản cần quyền đọc các mục thu thập. Host key phải được xác minh và lưu trong known_hosts theo [hướng dẫn SSH](ssh/HUONG_DAN_SSH.md).

```bash
.venv/bin/python main.py --check-connections --inventory inventory.local.yaml
.venv/bin/python main.py --collect --inventory inventory.local.yaml --output-dir reports/tv2-tv3
.venv/bin/python main.py --collect --inventory inventory.local.yaml --group lab --tag core --workers 2 --timeout 15
```

`inventory.local.yaml` là tên bản Inventory do người chạy chuẩn bị. Tham số `--known-hosts /path/to/known_hosts` dùng kho khóa đã xác minh riêng. `--frr-shell linux` hoặc `--frr-shell vtysh` chọn chế độ đăng nhập FRR, mặc định là `auto`.

Kiểm tra kết nối xuất `connections.json` và `connections.csv`. Thu thập xuất `collection.json` và `collection.csv`. Chạy lại cùng thư mục sẽ ghi đè hai báo cáo tương ứng. Có thể dùng thư mục khác cho mỗi lần chạy để giữ lịch sử. Báo cáo dùng bộ lọc dữ liệu của Collector TV3.

CLI trả mã thoát 0 khi các thiết bị hoàn thành, 1 khi có lỗi kết nối, thu thập, ghi log, đóng phiên hoặc xuất báo cáo, và 2 khi tham số không hợp lệ. Kết quả `partial` do mục `unsupported` hoặc trường `unavailable` vẫn có thể trả 0. Nếu một section có trạng thái `error`, CLI trả 1 và báo tên mục bị lỗi. Bộ lọc Inventory không chọn được thiết bị nào trả 1.

## Xử lý các trường hợp tích hợp

- MikroTik CHR có thể trả `routerboard: no`. Collector ghi serial là `unsupported`.
- Bảng ARP, MAC hoặc OSPF RouterOS rỗng được chuyển thành danh sách rỗng hợp lệ.
- FRR xuất JSON cho interface, route và OSPF. Các mục serial, ARP, MAC và discovery trong profile FRR được đánh dấu `unsupported`.
- Lệnh thu thập không được CLI thiết bị hỗ trợ tạo `UnsupportedFeatureError`. Lỗi quyền thực thi tạo `DeviceCommandError`. Collector ghi trạng thái cho từng mục và tiếp tục khi phiên còn sử dụng được.
- Timeout hoặc lỗi truyền dữ liệu đóng phiên. Các mục chưa đọc được vẫn ghi lỗi, dữ liệu đã thu thập được giữ lại.
- Adapter kiểm tra chính xác toàn bộ chuỗi lệnh. Các lệnh cấu hình, reboot và chuỗi nối thêm lệnh bị từ chối trước khi gửi qua SSH.
- Luồng lấy cấu hình bằng `get_running_config()` tiếp tục kiểm tra đầu ra RouterOS/FRR trước khi trả cho TV4.

## Kiểm thử

Chạy từ thư mục gốc repository.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python main.py --self-test
```

Các bài tích hợp dùng mã thực tế của TV2 và TV3, thay lớp truyền SSH Netmiko bằng mock. Phạm vi gồm hai nền tảng, ba chế độ FRR, kết nối bốn router đồng thời, cô lập lỗi xác thực, bảng rỗng, lệnh không hỗ trợ, lỗi lệnh, timeout, cleanup, lọc Inventory, xuất JSON/CSV và kiểm tra danh sách lệnh đọc.

Kết quả ngày 16/11/2026 với Python 3.13.12, Netmiko 4.8.0 và Paramiko 5.1.0 đạt 77 test, không có test bỏ qua. `main.py --self-test` đạt 4/4 FakeDevice.

Chưa nghiệm thu kết nối SSH trực tiếp tới router GNS3 trong lần ghép mã này. Kết quả mô phỏng không xác nhận trạng thái OSPF của lab.
