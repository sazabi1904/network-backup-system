# Checklist hoan thanh TV1 (4 tuan)

## Ngay 1
- [ ] Cai Python 3.9+, VS Code, Git
- [ ] Tao GitHub repository private `network-backup-system` (khong tao README online neu da import project co README)
- [ ] Giai nen project vao thu muc, `git init -b main`
- [ ] `git add .`, `git commit -m "Init TV1 core skeleton"`
- [ ] `git remote add origin <URL repo>`, `git push -u origin main`
- [ ] Moi 4 thanh vien tu Settings > Collaborators

## Ngay 2
- [ ] Chay `python main.py --self-test` va `python -m pytest -q`
- [ ] Review va chot `docs/API_CONTRACTS.md` voi ca nhom
- [ ] Moi thanh vien tu clone repo va chay test tren may minh
- [ ] Moi nguoi tao branch feature/...

## Tuan 1
- [ ] Them cac kieu TaskResult, ConfigSnapshot vao quy trinh tich hop
- [ ] Cung TV2 thong nhat DeviceFactory register adapter
- [ ] Cung TV3 thong nhat InventoryService.list_devices
- [ ] Cung TV4 va TV5 thong nhat Backup/Restore contracts

## Tuan 2
- [ ] Ghep menu CLI voi services cua TV3/TV4/TV5 neu PR da san sang
- [ ] Cac service goi interface, khong import truc tiep Netmiko
- [ ] Tai moi PR, `python -m pytest -q`, kiem tra coding style

## Tuan 3
- [ ] Test luong end-to-end FakeDevice roi GNS3
- [ ] Test device offline/timeout, backup failed, restore failed
- [ ] Xem log audit; dam bao khong lo password, token

## Tuan 4
- [ ] Ve UML Class Diagram va Sequence Diagram
- [ ] Hoan tat README, so do module, giao thuc, anh minh chung
- [ ] Dong bang chuc nang, tao release va tai ban ZIP truoc bao ve

**TV1 khong can code thay TV2-TV5.** Can quan ly interface, xu ly conflict va on dinh `main`.
