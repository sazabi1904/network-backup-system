# TV2–TV5: OSPFv2 backbone qua SSH thật

Bản này bổ sung deploy, read-back, restore và rollback OSPF cho RouterOS 7 / FRR 8.2.2. Nó thay thế trạng thái “chưa đạt OSPF thật” trong bản đối chiếu đầu ngày 18/11/2026. Identity/description tiếp tục dùng scope `managed`; OSPF dùng scope riêng `ospf`.

## Phạm vi

- RouterOS 7: instance `tv2-ospf`, area `tv2-backbone` (`0.0.0.0`), interface-template khớp IPv4 network. Cú pháp v6 `/routing ospf network` đã được thay thế.
- FRR: một process `router ospf` mặc định, router ID rõ ràng và các network ở backbone. Giữ ngữ cảnh `configure terminal → router ospf → exit → end` trong cùng lần gọi vtysh.
- Desired state thay thế phần OSPF được hỗ trợ, gồm thêm/sửa/xóa network; deploy lại cùng cấu hình không gửi lệnh thay đổi. Thay đổi một cấu hình khác sẽ tạo lại process/instance và có thể làm gián đoạn adjacency trong lúc hội tụ.
- Chặn cấu hình hiện có ngoài grammar trước khi ghi: instance MikroTik không thuộc phạm vi, area khác backbone, interface OSPF riêng, redistribution, authentication, filter, VRF hoặc process khác. Không tự xóa cấu hình production không nhận diện được.
- Không ghi IP/interface/ACL hoặc lưu startup FRR. RouterOS tự lưu thay đổi cấu hình theo cơ chế của hệ điều hành; không dùng reset/import toàn bộ router. Chưa kiểm thử reboot/persistence.

Backup TV4 được chọn bằng đúng snapshot ID và kiểm tra hash gốc. Restore thực hiện backup dự phòng, chỉ sửa phần OSPF và từ chối nếu cấu hình ngoài scope bị lệch. Xác minh cuối so toàn bộ cấu hình canonical: chỉ chuẩn hóa timestamp RouterOS, thứ tự thuộc tính/đối tượng OSPF và các giá trị mặc định đã biết; không bỏ qua network thừa hoặc tham số không hỗ trợ. FRR bỏ dòng phân cách `!`, giữ nguyên nội dung/ngữ cảnh cấu hình.

Khóa thao tác hiện áp dụng trong cùng một tiến trình Python. Chưa có khóa liên tiến trình hoặc cơ chế recovery qua console tự động khi mất đường quản trị.

## Chạy qua CLI hoặc menu

Inventory cục bộ và credential_ref theo hướng dẫn TV2/TV3. Cần host key đã xác minh. Mỗi router phải có router ID riêng; không suy router ID từ IP gateway localhost.

Ví dụ `ospf-r1.json`:

```json
{
  "router_id": "10.255.0.1",
  "networks": [{"prefix": "192.0.2.0/24"}]
}
```

Chỉ nhận `router_id`, `networks`; mỗi network nhận `prefix` và `area_id` tùy chọn phải là `0.0.0.0`. Các biến cũ như `areas`, `interfaces`, `cost` được từ chối để tránh âm thầm bỏ qua yêu cầu.

```sh
python cli.py --inventory inventory.local.yaml deploy --device R1 --template ospf --vars-file ospf-r1.json --write-scope ospf --known-hosts known_hosts.lab --dry-run
python cli.py --inventory inventory.local.yaml deploy --device R1 --template ospf --vars-file ospf-r1.json --write-scope ospf --known-hosts known_hosts.lab --confirm-write
python cli.py --inventory inventory.local.yaml restore --device R1 --snapshot-id SNAPSHOT_ID --backup-dir backups --write-scope ospf --known-hosts known_hosts.lab --confirm-write
```

Deploy mặc định xác minh cấu hình, trả `neighbor_convergence_checked=false`. Để bắt buộc neighbor hội tụ, thêm `--expected-neighbor 10.255.0.2` (lặp lại cho tất cả peer) và tùy chọn `--convergence-timeout 90`. Nếu chưa hội tụ trong thời hạn, TV5 rollback về snapshot trước deploy. Khi triển khai ban đầu, cần cấu hình các peer trước hoặc dùng runner nhiều thiết bị bên dưới.

`python main.py` → TV5: mục 7 deploy OSPF, mục 8 restore OSPF. Mục 5/6 dành cho identity/description.

## Nghiệm thu nhiều router

```sh
python -m pytest -q
python -m TV2.ssh.ospf_acceptance --inventory inventory.local.yaml --plan ospf-plan.json --known-hosts known_hosts.lab --confirm-write
```

Plan JSON ánh xạ tên inventory sang `variables`, `expected_neighbors`, `expected_routes` tùy chọn và `ping_targets` tùy chọn. Ví dụ hai router có sẵn địa chỉ mạng tương ứng:

```json
{
  "R1": {"variables": {"router_id": "10.255.0.1", "networks": [{"prefix": "192.0.2.0/24"}]}, "expected_neighbors": ["10.255.0.2"]},
  "R2": {"variables": {"router_id": "10.255.0.2", "networks": [{"prefix": "192.0.2.0/24"}]}, "expected_neighbors": ["10.255.0.1"]}
}
```

Runner preflight/backup mọi router trước khi thay đổi, deploy và thử idempotence, chờ neighbor/route, ping các đích chỉ định, cố ý làm verifier thất bại sau thay đổi network, xác minh rollback về OSPF đang hoạt động rồi chờ hội tụ lại. Cuối cùng restore baseline ban đầu trong `finally` cho từng thiết bị.

Trên mạng broadcast, DROther–DROther có thể ở 2-Way: tiêu chí là mọi peer dự kiến đạt FULL/2-Way và có ít nhất một FULL adjacency. Route dự kiến phải là route OSPF được chọn; ping phải nhận đủ 3/3 gói. Lỗi xác minh trong bước controlled failure là lỗi được tạo có chủ đích.

## Kết quả nghiệm thu ngày 18/11/2026

- **177 test tự động PASS**; xem [pytest-ospf.txt](evidence/20261118/pytest-ospf.txt).
- **4/4 router SSH thật PASS**: MikroTik-R1/R2 (RouterOS 7.23.8), FRR-R3/R4 (FRR 8.2.2).
- Cả bốn đạt deploy/read-back, idempotence, neighbor và route OSPF, ping đủ 3/3 gói mỗi đích.
- Cả bốn đạt thay đổi network rồi rollback có chủ đích về snapshot OSPF đang hoạt động, và hội tụ lại sau rollback.
- Cả bốn restore baseline ban đầu, toàn bộ cấu hình canonical khớp snapshot (`exact_hash_match=true`). Sau gỡ fixture đã kiểm tra lại cấu hình gốc trên từng router và đều khớp.

Lab dùng LAN 192.168.77.0/24 hiện có. Để có route từ xa thực sự, bài thử thêm tạm địa chỉ 10.255.0.3/32 và 10.255.0.4/32 trên lo của hai FRR qua console; adapter chỉ quảng bá các network này. MikroTik học cả hai route; mỗi FRR học route loopback của FRR còn lại. Có 6 đích ping, tổng 18/18 gói nhận. Địa chỉ tạm đã được gỡ và OSPF thử nghiệm đã restore về baseline, không lưu startup FRR.

[Bằng chứng JSON cuối cùng](evidence/20261118/ospf.json) chứa kết quả từng bước, snapshot ID và trạng thái xác minh; không chứa credentials hoặc raw config. Các lần chạy trước đã phát hiện/sửa RouterOS bỏ area-id mặc định và FRR dùng wrapper neighbors/trường state; đã bổ sung test hồi quy. Lần chạy cuối PASS toàn bộ sau các sửa này.

## Tài liệu nền tảng

- [RouterOS 7 OSPF instance, area và interface-template](https://help.mikrotik.com/docs/spaces/ROS/pages/9863229/OSPF).
- [FRR 8.2 OSPFv2](https://docs.frrouting.org/en/stable-8.2/ospfd.html).
