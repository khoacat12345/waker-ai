# v1.0.0 — Final Acceptance Report

**Dự án:** waker-ai
**Repo:** `C:\Users\tuank\waker-ai` → `https://github.com/khoacat12345/waker-ai`
**Tag:** `v1.0.0`
**Ngày:** 2026-11-08
**Trạng thái:** ✅ HOÀN TẤT — `pytest tests/` exit code **0**
**Dừng tại:** release draft + tag; **chưa publish PyPI** (chờ token/trusted publisher).

---

## 1. Kết quả kiểm thử

```
127 passed, 1 skipped in 69.32s
EXIT CODE = 0
```

| Thông số | Giá trị |
|---|---|
| Automated tests | **127 passed** |
| Skipped | 1 (`test_live_opencode`, gate `WAKER_LIVE_TEST=1`) |
| New tests in v1.0 | **17** (planner bridge, detect, resume, CLI) |
| Exit code | **0** |
| Wheel | `waker_ai-1.0.0-py3-none-any.whl` — 70.472 bytes |
| SHA256 | `adb2eeaebb7fdcfa0f4654fc61d4fba0dbcbc927f54dfc2aec8d60217df7a499` |

---

## 2. Ba lỗ hổng sản phẩm đã vá

### 2.1 `waker plan --via opencode` — prompt mơ hồ

Một turn OpenCode viết `tasks.yaml`, sau đó **linter deterministic** kiểm tra.
LLM đề xuất, máy phán quyết.

**Chạy thật** (repo temp, prompt: "Làm module auth đơn giản: login, logout,
session; viết test cho nó; đừng dùng thư viện ngoài."):

```
[waker] plan: $0.0055, 28226 tokens
# đã ghi .waker\tasks.yaml
```

Kết quả — 2 task + 1 constraint, có scope và verify thật:

```yaml
- id: T1
  scope: [src/auth/**]
  verify: python -c "from src.auth import AuthManager; ... assert a.session(t) is None"
- id: T2
  scope: [tests/**]
  verify: python -c "import unittest; ... sys.exit(0 if res.wasSuccessful() and res.testsRun >= 4 else 1)"
  depends_on: [T1]
- id: C1
  kind: constraint
  check: python -c "import ast,sys,...; bad=sorted(...); sys.exit(1 if bad else 0)"
```

```
$ waker lint --tasks .waker/tasks.yaml --repo .
OK: contract hợp lệ
EXIT=0
```

→ Chứng minh: prompt tự do → contract máy kiểm được, không cần người viết tay
scope/verify. Chi phí một lần lập kế hoạch: **$0.0055**.

### 2.2 `waker run --resume <id>` — khôi phục sau gián đoạn

- State, ledger, session id, cost, verify cache, fingerprint được nạp lại.
- `generation` tăng; kick dir thành `kick-N-g1` để **không ghi đè audit cũ**.
- Mặc định cấp lại budget (`kicks + max_kicks`); `--max-kicks` cho phép đặt tuyệt đối.

**Test E2E:** chạy lười với `--max-kicks 0` → `BREAKER`; resume → agent làm nốt
task 2 → `DONE`, cùng `run_id`, có event `resume` (`generation=1`,
`previous_status=BREAKER`).

### 2.3 `waker detect`

```
$ waker detect --repo .
 75%  pytest -q                (tests/ directory)
EXIT=0
```

Hỗ trợ pytest / npm / cargo / go / make; in confidence + nguồn.

---

## 3. Publish & Launch assets

| Việc | Trạng thái |
|---|---|
| `.github/workflows/publish.yml` | ✅ build sdist+wheel, `twine check`, Trusted Publishing (OIDC) + fallback `PYPI_API_TOKEN` |
| Demo GIF | ✅ `docs/demo.gif` — 137.912 bytes, 7 frame, tự sinh bởi `scripts/make_demo_gif.py` |
| GIF trong README | ✅ ngay dưới badge |
| Script quay 45s | ✅ `docs/demo-45s.md` |
| Version 1.0.0 | ✅ `pyproject.toml`, `__init__.py` |
| CHANGELOG | ✅ `CHANGELOG.md` |
| Release notes | ✅ `docs/release-v1.0.0.md` |

---

## 4. Tài liệu hoá trung thực

| Hạng mục | Ghi rõ |
|---|---|
| Claude T1 | **Beta** — unit-tested, chưa có live E2E vì máy build không cài `claude` |
| Cost Guard | Chính xác với OpenCode (`session export`); best-effort với Claude (`total_cost_usd` delta); 0 với generic/PTY |
| PTY T3 | Windows-only (ConPTY); POSIX để v1.1 |
| PyPI | Workflow sẵn sàng; chưa publish vì cần token/trusted publisher của chủ repo |

README có bảng Adapters kèm cột **Status** và mục **Maturity**.

---

## 5. Quy trình đã chạy

1. Viết code + 17 test mới.
2. `pytest tests/` → 127 passed, 1 skipped, exit 0.
3. Build wheel 1.0.0, kiểm tra nội dung (có `llm_plan.py`, `detect.py`, 4 skill templates).
4. Chạy thật `plan --via opencode` + `detect` + `lint` trên repo temp.
5. Commit milestone, tag `v1.0.0`, push `main` + tag.
6. Tạo **draft release** kèm wheel (chưa publish để tránh chạy publish workflow khi PyPI chưa cấu hình).
7. Báo cáo này.

---

## 6. Giới hạn còn lại (không chặn v1.0)

- Claude chưa có live E2E → giữ nhãn beta.
- PTY chưa có trên POSIX.
- `plan --via opencode` tốn ~$0.005/lần và có thể tạo contract dở; linter chặn
  nếu thiếu scope/verify. Người dùng luôn được xem `tasks.yaml` trước khi chạy.
- Daemon/dashboard không auth (loopback).
- Chưa có coverage gate trong CI.

---

## 7. Việc còn lại để “tung hô” (cần chủ repo)

1. Cấu hình PyPI Trusted Publisher (hoặc thêm secret `PYPI_API_TOKEN`).
2. Publish draft release `v1.0.0` → workflow `publish` tự đẩy lên PyPI.
3. Đổi README sang `pip install waker-ai` sau khi PyPI có bản 1.0.0.
4. Quay video 45s theo `docs/demo-45s.md` (GIF đã có sẵn).
5. Đăng launch (Show HN, Reddit, X) — dùng câu chuyện “agent bỏ việc sau 14 phút”.

---

## 8. Checklist nghiệm thu

- [x] `waker plan --via opencode` + linter
- [x] `waker run --resume <id>` + audit generation
- [x] `waker detect`
- [x] Claude ghi rõ Beta; Cost Guard ghi rõ phạm vi
- [x] `publish.yml` (trusted publishing + token fallback)
- [x] `docs/demo.gif` + README + `docs/demo-45s.md`
- [x] Version 1.0.0 + CHANGELOG + release notes
- [x] 127 tests pass, exit 0
- [x] Wheel 1.0.0 build sạch
- [x] Tag `v1.0.0` + push
- [x] Draft release + wheel
- [x] Báo cáo này
