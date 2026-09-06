# Kế hoạch theo giai đoạn — công việc còn lại (2026-09-05)

Tài liệu tổng quyền: `plan/remaining-work-handoff-2026-09-05.md` (87 dòng).
Tài liệu này CHỈ là kế hoạch: không cài đặt, không chạy gate, không commit/push.

## Trạng thái lập kế hoạch
- Lập kế hoạch: **DONE — REVISED** (bản sửa theo phản hồi 2026-09-05; đây là sửa KẾ HOẠCH, KHÔNG phải hoàn thành triển khai).
- Đường cơ sở: main sạch tại `319a442`. Các commit nhánh `work/holdout-honesty-gates` trong handoff là **LỊCH SỬ**; phải kiểm chứng hiện trạng trên HEAD trước khi tin (P1-T1).

## 1. Bất biến áp dụng mọi phase (vi phạm ⇒ gate FAIL)
- **INV-1** Không sửa file lịch sử: baseline pack, oracle fixture, `benchmarks/holdout_unseen`. SHA-256 manifest holdout: `db0e8324de2a6355b8aba52b0937996795fac098237740369ded0d0870a73919`.
- **INV-2** SG-202: số liệu lịch sử — 90 task / 1500 token / sàn 95%; 34/42 (42 đo được gốc); 35/43 (43 đo được hiện tại); 35/90 (toàn mẫu); 17/35 thành công khi nguồn rút gọn — là bằng chứng đóng băng, cấm trộn cohort; lượt LẬP KẾ HOẠCH này không rerun. Khi triển khai, BẮT BUỘC replay lại NGUYÊN protocol không đổi (roster 90 / 1500 token / oracle sàn 95%) vào thư mục output MỚI, duy nhất, KHÔNG BAO GIỜ ghi đè bằng chứng cũ, rồi sao chép log/artifact vào nơi bền vững (không chỉ /tmp):
  `.venv/bin/python benchmarks/exit_gates/sg202_followup/replay_sg202.py --root . --output-dir /tmp/sg202-pN-unique`
- **INV-3** Frozen replay truyền mục tiêu bare-name ⇒ qualified selector **một mình không thể** sửa 3 ca `AMBIGUOUS_TARGET` (`as_dict`, `_tag`, `__exit__`) trong replay đóng băng. Bắt buộc giữ fail-closed. Replay selector-định-danh hoặc đổi ngữ nghĩa usage-oracle phải là thí nghiệm **phiên bản riêng** (tên + manifest riêng); cấm nhãn "frozen trước–sau"; cấm hứa SG-202 PASS.
- **INV-4** 5 ca `MISSING_TEST` (`CoverageState`, `Claim`, `FreshnessStatus`, `_ConnView`, `_index_binding`): chỉ chấp nhận bằng chứng usage thật hoặc cải thiện extraction chính đáng. Cấm caller edge giả; tách typed usage khỏi calls; test hành vi thật, không độn điểm.
- **INV-5** Không di trú monorepo Python/C trong phạm vi này; `plan/python-c-monorepo-architecture-plan-2026-09-05.md` GIỮ NGUYÊN, ngoài phạm vi (không xóa, không sửa).
- **INV-6** Lượt này không commit/push; mỗi phase chỉ ĐỀ XUẤT ranh giới commit logic; commit thật cần chấp thuận riêng khi triển khai.
- **INV-7** Log bền vững, tên riêng theo phase (`logs/ph<N>-<mục-đích>-<ngày>.log`); cấm trữ chỉ ở `/tmp`.
- **INV-8** Cổng con người: ≥3 người thật, precision@20 ≥90%, tổng hợp chỉ sau xác minh thủ công. CẤM agent giả người; CẤM CSV ĐÃ ĐIỂM/attestation do agent tạo; SINH worksheet TRẮNG theo protocol là được phép. Chuẩn bị chạy được từ P1; kết luận cho ranking thay đổi cần manifest MỚI + reviewer thật.
- **INV-9** Ủy quyền: `pack.py` một tác giả duy nhất; extraction owner chỉ nghiên cứu/test, không sửa production dùng chung đồng thời; tối đa 3 tác giả song song, file rời rạc; DB/reconcile/registry dùng chung chỉ main chạm; người đọc dùng snapshot đóng băng.

## 2. Bảng trạng thái
| Hạng mục | Trạng thái |
| --- | --- |
| Lập kế hoạch (tài liệu này) | DONE |
| P1 Đường cơ sở & hợp đồng | NOT_STARTED |
| P2 SG-202 định danh + usage thật | NOT_STARTED |
| P3 SG-202 chất lượng nguồn + nghiệm thu độc lập | NOT_STARTED |
| P4a Claims bằng chứng lịch sử | NOT_STARTED |
| P4b SG-301 characterization | NOT_STARTED |
| P5 Federation provider ngoài thật | NOT_STARTED |
| P6a Repo-map đa tín hiệu | NOT_STARTED |
| P6b SG-201 nghiên cứu người thật (version-bound) | NOT_STARTED |
| P7 Hợp nhất bằng chứng + quyết định governance | NOT_STARTED |

Handoff của phase chỉ được tạo khi phase chạy, theo template §12; cấm viết "hoàn thành" khi gate chưa có bằng chứng.

## 3. DAG phụ thuộc (plain text)

**Quy tắc điều phối ưu tiên:** giới hạn 3 tính theo tác giả đang ghi file, không theo số lane. Trong wave P2 + P4a + P4b, P2-T2 và P2-T3 triển khai tuần tự, chuyển quyền ghi sau khi tác giả trước dừng; P4b cũng chỉ có một tác giả đang ghi tại một thời điểm. Nghiên cứu read-only có thể song song. P4b được viết test trong wave này nhưng KHÔNG thu baseline/đo characterization trên working tree đang thay đổi: chỉ đo khi main đã đóng băng snapshot tích hợp, mọi tác giả production tạm dừng và mọi phụ thuộc hành vi của CLI/MCP (kể cả pack/extraction) ổn định. Sau đó chạy lại baseline trên snapshot trước mỗi split.
```text
Wave 1: P1 (baseline mới + hợp đồng)
Wave 2 (tối đa 3 lane song song): P2 + P4a + P4b
Wave 3: P3 (sau P2; nghiệm thu batch)
Wave 4: P5 + P6 — production: P3 ──► P5, P3 ──► P6a là ràng buộc CỨNG (read-only prep sau P1)
P6a freeze (đóng băng manifest) ──► P6b evaluation (chấm thật)
P4b: characterization snapshot TUẦN TỰ hóa thay đổi hành vi dùng chung;
     split (P4b-T5) chỉ sau các lane production liên quan nghỉ (quiescent)
mọi lane ──► P7 (báo cáo nhận mọi trạng thái, gồm cả BLOCKED)
```

## 4. P1 — Đường cơ sở & hợp đồng
- **Mục tiêu**: chốt hiện trạng thật trên HEAD + baseline MỚI + hợp đồng làm việc trước mọi code.
- **Tasks**:
  - `P1-T1` Kiểm kê HEAD `319a442`: xác nhận `src/sot_graph/pack.py`, `repo_map.py`, `provider_contract.py`, `db.py`, `cli.py`, `mcp_service.py`, `diff_impact.py`; `scripts/bench_provider_identity.py`, `scripts/e2e_real_cbm.py`, `scripts/quality_gates.sh`; tests hiện có (`tests/test_pack_sg202_priority.py`, `tests/test_sg202_pack_completeness.py`, `tests/test_sg110_claims.py`, `tests/test_repo_map.py`); artifacts `benchmarks/exit_gates/sg202_followup/`. Ghi chênh lệch so với handoff lịch sử; CHỐT đường dẫn production cho P2. Ownership: main.
  - `P1-T2` Baseline TƯƠI (1578 passed / 2 skipped lịch sử KHÔNG phải kết quả mới): full `.venv/bin/python -m pytest tests/ -q`; `bash scripts/quality_gates.sh` (theo §11); frozen replay SG-202 nguyên protocol vào output MỚI duy nhất (lệnh ở INV-2). Log/artifact bền vững `logs/ph1-*`. Ownership: tester độc lập.
  - `P1-T3` Văn bản hợp đồng INV-1..9 + quy ước đặt tên thí nghiệm phiên bản (`<gate>-<ý-đồ>-v<N>`). Ownership: main.
  - `P1-T4` Hạ tầng log bền vững `logs/` + template handoff §12. Ownership: main (doc-only).
  - `P1-T5` Chuẩn bị cổng con người — chỉ PREP, KHÔNG chặn exit P1: giữ nguyên manifest/worksheet hiện có; chỉ sinh worksheet TRẮNG theo protocol; tuyển reviewer thật kéo dài đến P6b. Ownership: human-prep lane.
- **Test**: chỉ thay đổi chủ ý (không yêu cầu cây sạch vì phase này không commit).
- **Exit gate**: INV được duyệt; baseline P1-T2 có kết quả MỚI + log bền vững; inventory P1-T1 xác nhận/sửa giả định đường dẫn. Tuyển reviewer KHÔNG phải điều kiện chặn.
- **Handoff**: `plan/handoff-p1-baseline-contracts.md`.
- **Commit đề xuất**: 1 commit docs (hợp đồng + logs + template) nếu được chấp thuận; artifact replay/baseline mới theo nhóm riêng.

## 5. P2 — SG-202: định danh tường minh + usage thật
- **Mục tiêu**: xử lý đúng bản chất 8 ca fail hiện tại mà không vi phạm INV-2/3/4.
- **Tasks**:
  - `P2-T1` Audit hỗ trợ định danh hiện tại trong search/pack TRƯỚC khi thêm gì; đường dẫn production CHỐT theo inventory P1; cấm gọi oracle giả. Ownership: research owner, read-only, receipt ≤500 token.
  - `P2-T2` CÀI ĐẶT (không chỉ thiết kế) qualified identity selection tường minh sau audit: không chọn ứng viên tùy tiện, giữ fail-closed; công bằng interface CLI/MCP (parity) khi cần. File lõi `pack.py`: MỘT owner duy nhất, làm TUẦN TỰ. Ownership: tác giả duy nhất của `pack.py`.
  - `P2-T3` Giai đoạn RIÊNG sau khi hợp đồng usage được review: HIỆN THỰC HÓA bằng chứng usage thật cho 5 MISSING_TEST — typed usage tách khỏi calls; cải thiện extraction nếu chính đáng. Ownership: extraction owner (không sửa production dùng chung đồng thời với P2-T2).
  - `P2-T4` Test hành vi thật, ví dụ `tests/test_sg202_usage_evidence.py` mới; giữ pass test cũ; test parity CLI/MCP cho selector.
- **Test**: full pytest; case âm chứng minh usage giả phải bị từ chối (không độn điểm).
- **Exit gate**: §11 đạt tường minh; fail-closed còn nguyên cho 3 ambiguous; không replay nào bị gán nhãn frozen before–after; thí nghiệm selector (nếu chạy) mang phiên bản riêng; logs bền vững.
- **Handoff**: `plan/handoff-p2-sg202-identity-usage.md`.
- **Commit đề xuất**: checkpoint nhóm logic đã nghiệm thu NGAY trong phase nếu được chấp thuận; nếu không — bàn giao diff bounded; cấm dồn thay đổi phụ thuộc sang P3.

## 6. P3 — SG-202 chất lượng nguồn + nghiệm thu độc lập
- **Mục tiêu**: nguồn substantive thật, giữ metadata partial/line-count; nghiệm thu độc lập toàn batch.
- **Tasks**:
  - `P3-T1` Gate chất lượng nguồn: dev sample KHAI BÁO TRƯỚC; tiêu chí thân nguồn HỮU DỤNG (useful bodies) + accounting partial + không thoái lui budget — KHÔNG dùng check nonempty-source làm tiêu chí. Sửa trong `pack.py` (một tác giả, không ai sửa song song).
  - `P3-T2` Nghiệm thu độc lập theo §11 (tester ≠ author ≠ reviewer); receipt author vào hàng đợi main; main tuần tự hóa reconcile/doctor/diff-impact sau snapshot tích hợp đóng băng.
  - `P3-T3` Main review diff thật; tổng hợp trạng thái: replay đóng băng mục tiêu ≥95% trên cohort 42 GỐC (sàn 95%), các mẫu số 42/43/90 báo cáo RIÊNG BIỆT; protocol mới là thí nghiệm phiên bản riêng. Cấm tuyên bố PASS TRƯỚC khi có bằng chứng replay đạt — KHÔNG cấm vĩnh viễn; product FAIL không chặn lane độc lập.
- **Exit gate**: §11 đạt tường minh; acceptance độc lập đạt; gate nguồn đạt theo tiêu chí đã khai báo; cohort không trộn; mọi replay mới có nhãn phiên bản.
- **Handoff**: `plan/handoff-p3-sg202-source-acceptance.md`.
- **Commit đề xuất**: checkpoint nhóm logic riêng — identity; usage; source — ngay sau acceptance từng nhóm nếu được chấp thuận; nếu không — diff bounded, không tích lũy.

## 7. P4 — Hai lane độc lập (P4a claims, P4b characterization)
Song song, tác giả khác nhau, file rời rạc; DB/reconcile/registry chỉ main chạm.
- **P4a — Claims bằng chứng lịch sử** (owner: `claims.py` + tests):
  - `P4a-T1` Phân loại claim: historical artifact commit vs implementation commit; mở rộng `tests/test_sg110_claims.py` + claims lint đối chiếu snapshot artifact lịch sử (không chỉ ancestry/giá trị hiện tại).
  - `P4a-T2` Case âm bắt buộc: artifact THIẾU, snapshot NÔNG (shallow), LỆCH lịch sử (history mismatch) đều phải FAIL lint.
  - `P4a-T3` Migration schema phải chứng minh không rewrite measurement cũ (test so snapshot trước/sau); CẤM sửa điểm registry TỰ ĐỘNG — mọi thay đổi điểm qua review.
  - Gate: §11 đạt tường minh; claims lint pass + đủ case âm; test migration xanh. Handoff: `plan/handoff-p4a-claims-history.md`.
- **P4b — SG-301 characterization** (trước khi tách module hot-spot):
  - `P4b-T1..T4` Test characterization riêng từng file cho `db`, `cli`, `mcp_service`, `diff_impact` (vd `tests/characterization/test_<module>_characterization.py`); chỉ normalize nondeterminism được duyệt (danh sách ghi trong handoff); production ĐÓNG BĂNG khi đo.
  - `P4b-T5` Subphase có giới hạn: splitting theo acceptance, TỪNG MODULE MỘT, chỉ sau gate của module đó đạt VÀ các lane production liên quan đã nghỉ (quiescent).
  - Gate: §11 đạt tường minh; characterization ổn định 2 lần chạy liên tiếp; SAU MỖI lần split (P4b-T5): chạy lại characterization 2 lần + full gates; CẤM cập nhật golden để che thoái lui; không refactor trước khi gate đạt. Handoff: `plan/handoff-p4b-sg301-characterization.md`.

## 8. P5 — Federation provider ngoài THẬT
- **Phụ thuộc CỨNG**: thay đổi production chỉ sau P3; sau P1 chỉ được chuẩn bị read-only (audit/kế hoạch).
- `P5-T1` Audit năng lực hiện tại của `src/sot_graph/provider_contract.py`, `scripts/bench_provider_identity.py`, `scripts/e2e_real_cbm.py`; claim roadmap lịch sử có thể stale — audit trước, báo cáo chênh lệch.
- `P5-T2` Corpus ngoài thật + chạy e2e thật, tái sử dụng script trên; bằng chứng seeded/synthetic chỉ là sensitivity, KHÔNG tính external acceptance.
- `P5-T3` So sánh chồng lấn CBM THẬT VÀ SCIP THẬT: precision/recall/conflicts so với ground truth định danh canonical; manifests/pins đóng băng; NGƯỠNG ĐÓNG BĂNG TRƯỚC khi đo; cấm tune trên holdout unseen.
- **Exit gate**: §11 đạt tường minh; CẢ CBM lẫn SCIP có bằng chứng external thật (không synthetic) kèm manifest SHA; thiếu môi trường ⇒ trạng thái BLOCKED (không PASS); báo cáo không định lượng vượt mẫu.
- **Handoff**: `plan/handoff-p5-external-federation.md`.

## 9. P6 — Hai lane
- **P6a — Repo-map đa tín hiệu** (production CHỈ sau P3 — ràng buộc CỨNG; read-only prep sau P1):
  - `P6a-T1` Dev-set nội bộ + ablation để CHỌN tín hiệu trong `src/sot_graph/repo_map.py` + `tests/test_repo_map.py`; tiêu chí gain + không-thoái lui KHAI BÁO TRƯỚC khi tune; cấm hứa weights suy đoán; docs chỉ viết theo kết quả ablation.
  - `P6a-T2` Gate ô nhiễm: default <2%, tối thiểu 50 symbol/cell, budget 1024/2048; budget root cô lập tất định + filter production; ghi nhận giới hạn corpus 11 repo hiện có (ít fixture/vendor chứa symbol ⇒ sensitivity hạn chế).
  - `P6a-T3` Đóng băng manifest phiên bản MỚI cho ranking thay đổi; kết luận chấp nhận chỉ khi có reviewer thật (ghép P6b).
  - Gate: §11 đạt tường minh. Handoff: `plan/handoff-p6a-repo-map-ranking.md`.
- **P6b — SG-201 nghiên cứu người thật (version-bound)**:
  - `P6b-T1` Đóng băng manifest phiên bản (roster + phiên bản sản phẩm), SHA ghi trong báo cáo.
  - `P6b-T2` ≥3 người thật chấm theo protocol; precision@20 ≥90%; tổng hợp CHỈ sau xác minh thủ công; cấm CSV agent.
  - Gate: manifest đóng băng + SHA; đủ reviewer thật; aggregate đã xác minh tay. Handoff: `plan/handoff-p6b-sg201-human-study.md`.

## 10. P7 — Hợp nhất bằng chứng + quyết định governance
- `P7-T1` Hợp nhất bằng chứng mọi phase: bảng trạng thái gate cuối (NOT_STARTED / IN_PROGRESS / PASS / FAIL / BLOCKED), mỗi dòng kèm artifact + SHA; claims chỉ trong phạm vi bằng chứng.
- `P7-T2` Governance: quyết định THẬT với chủ sở hữu thật — CODEOWNERS owner, SECURITY contact, Dependabot ecosystem, lựa chọn SBOM/provenance. Không bịa giá trị; không chặn lane độc lập đang chạy; giá trị thiếu ghi PENDING kèm người phụ trách.
- `P7-T3` Tổng kết: danh sách việc còn lại + handoff cuối; không tự gán PASS cho cổng chưa có bằng chứng.
- **Exit gate**: báo cáo tổng nhất quán với từng handoff phase; mọi mục governance là quyết định có người xác nhận hoặc PENDING.
- **Handoff**: `plan/handoff-p7-consolidation-governance.md`.

## 11. Quy tắc ủy quyền & nghiệm thu (mọi phase có code)
- Trước khi giao việc triển khai: `sot search` + `sot pack "<symbol>" --tokens 1500` (không cần cho việc doc-only); receipt trả về ≤500 token; khi sửa lỗi → tiếp tục cùng agent.
- Nghiệm thu chuẩn — BẮT BUỘC cho mọi exit gate có code, handoff ghi tường minh "§11 đạt": full `.venv/bin/python -m pytest tests/ -q`; `bash scripts/quality_gates.sh` (core ≥85, receipts ≥90); lint/type phạm vi cho file ngoài gate; claims lint; gate chính đọc artifact/log BỀN VỮNG per-phase (không chỉ /tmp).
- Tuần tự hóa main: receipt nghiệm thu của author vào hàng đợi main; main chạy `sot reconcile` + `sot doctor` + `sot diff-impact` TUẦN TỰ sau khi chốt snapshot tích hợp đóng băng.
- Gate code FAIL ⇒ CÁCH LY lane: dừng tích hợp phụ thuộc; author cũ tiếp tục sửa rồi re-test. Gate SẢN PHẨM FAIL (vd SG-202) được tồn tại song song với code đã chấp nhận — ghi nhận liên tục, không cấm vĩnh viễn lane độc lập.
- Checkpoint phase: nếu được chấp thuận, commit nhóm logic đã nghiệm thu NGAY trong phase; nếu không — bàn giao diff bounded; CẤM tích lũy thay đổi phụ thuộc băng qua phase.
- Nhãn owner theo lane: author/tester/reviewer/human-prep (agent ID gán khi spawn, ghi trong handoff); DAG không hàm ý mọi lane chạy đồng thời — theo Wave §3, tối đa 3 lane; tối đa 3 tác giả song song, file rời rạc; người đọc dùng snapshot đóng băng; DB/reconcile/registry chỉ main.

## 12. Template handoff dùng lại (1–2 trang mỗi phase, điền khi phase chạy)
```markdown
# Handoff P<N> — <tên> — <ngày>
1. Phạm vi & kết quả (chỉ ghi cái CÓ BẰNG CHỨNG; cấm "hoàn thành" nếu gate chưa chạy)
2. Baseline: HEAD SHA + worktree sạch lúc bắt đầu
3. Ownership: file → tác giả (≤3 người, file rời rạc; pack.py một tác giả)
4. Task IDs P<N>-T*: trạng thái từng task
5. Tests đã chạy + kết quả (đường dẫn log bền vững, không /tmp)
6. Exit gates: từng gate — ĐẠT/CHƯA ĐẠT + bằng chứng
7. Bất biến INV-1..9: xác nhận không vi phạm
8. Ranh giới commit ĐỀ XUẤT (không commit nếu chưa được chấp thuận)
9. Việc còn treo + agent phụ trách (resume cùng agent khi sửa)
```

## 13. Điều không làm (nhắc lại)
Lượt LẬP KẾ HOẠCH này không rerun SG-202; khi triển khai phải replay NGUYÊN protocol vào output MỚI duy nhất, không ghi đè bằng chứng; không trộn cohort; không hứa PASS khi chưa có bằng chứng (không cấm vĩnh viễn). Không caller edge giả; không CSV đã điền/attestation do agent tạo (worksheet TRẮNG được phép); không sửa baseline/oracle/holdout. `plan/python-c-monorepo-architecture-plan-2026-09-05.md` GIỮ NGUYÊN, ngoài phạm vi. Không commit/push trong lượt này; cấm tích lũy thay đổi phụ thuộc băng qua phase.
