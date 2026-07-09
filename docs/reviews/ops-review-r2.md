# Operations Review Round 2: khub M1 — Fix Verification

- **Reviewer**: CodeBuddy (ops review agent, R2)
- **Date**: 2026-07-09
- **Reviewed artifact**: `/home/keen/khub/docs/superpowers/plans/2026-07-07-khub-m1.md`
- **Baseline**: R1 findings at `/home/keen/khub/docs/reviews/ops-review.md`

---

## 1. Test/Implementation Mismatch (R1: high) — click vs argparse

**Finding**: R1 identified test code using `click.testing.CliRunner` while the CLI implementation used `argparse`, and `click` was not in dependencies.

**Updated Plan**: Task 9 (line 1000) rewrites `tests/test_cli.py` to use `subprocess.run([sys.executable, "-m", "khub.cli", ...])` exclusively. No `click` imports anywhere. `pyproject.toml` (line 60) lists only `PyYAML>=6.0,<7` as runtime dependency.

**Verdict**: **Fixed**

**Note**: CLI tests use argparse + subprocess as recommended. No click dependency leakage.

---

## 2. E2E Test Writes to Production DB (R1: high)

**Finding**: R1 flagged the e2e smoke test using `KHUB_CONFIG=""` which triggered the fallback to `/home/keen/khub/khub.db`.

**Updated Plan**: The e2e test (Task 10, line 1137) and CLI tests (Task 9, line 1008) now set `KHUB_CONFIG=str(tmp_path / "empty.yaml")`. However, **`empty.yaml` is never created** — it's a non-existent file. In `_store()` (line 1061):

```python
if not os.path.exists(CONFIG_PATH):
    print(f"警告: 配置文件 {CONFIG_PATH} 不存在，使用默认配置", file=sys.stderr)
    return Store("/home/keen/khub/khub.db")
```

This means the tests still fall back to the **production DB path** `/home/keen/khub/khub.db` when the config file doesn't exist. The `db = tmp_path / "k.db"` variable on line 1009 is declared but never used.

**Verdict**: **Not fixed**

**Note**: The approach is directionally correct (use `tmp_path` + `KHUB_CONFIG`), but the tests must either (a) create a YAML file at the config path that specifies a `tmp_path`-based DB, or (b) the CLI needs a `--db` flag. Without this, running the test suite will corrupt or overwrite the user's real database.

---

## 3. No Logging (R1: high)

**Finding**: R1 required logging throughout engine and CLI — sync start/end, doc counts, durations, adapter errors, and `logging.basicConfig` in CLI `main()`.

**Updated Plan**:
- `ocr.py` (line 580): One `logging.warning` call for skipped attachments. ✅
- `cli.py` (line 1062): `print(f"警告: ...", file=sys.stderr)` for missing config. ✅
- Everything else: **Still no `import logging`** in `engine.py`, `db.py`, or `cli.py` `main()`.
- No `logging.basicConfig(level=logging.INFO)` in CLI `main()`.
- No `--verbose`/`-v` flag.
- `engine.py` has zero logging — sync start/end, doc counts, skipped docs, adapter errors are all silent.
- `db.py` has zero logging.

**Verdict**: **Partial**

**Note**: One `logging.warning` was added to `ocr.py`, which is the bare minimum. But the engine and CLI still lack structured logging. Critical operations (sync start/end, doc counts, adapter failures) remain invisible without re-running with print statements. The R1 recommendation of `logging.basicConfig` in `main()` and a `--verbose` flag was not implemented.

---

## 4. No Schema Migration (R1: high)

**Finding**: R1 required a `schema_version` table and migration logic to support future schema changes.

**Updated Plan**: `Store.init_schema()` (line 180) uses `CREATE TABLE IF NOT EXISTS` exclusively for all 7 tables. There is **no `schema_version` table**, no version check in `Store.__init__()`, and no migration path.

**Verdict**: **Not fixed**

**Note**: The plan acknowledges that M2+ will add columns and tables, but the migration mechanism recommended in R1 was not implemented. Adding columns to existing databases in M2+ will require manual intervention. This is a high-severity issue because the design spec's "never lose content" guarantee cannot be upheld without a migration strategy as the schema evolves.

---

## 5. Runtime FTS5 Check (R1: medium)

**Finding**: R1 recommended a runtime FTS5 check in `Store.__init__()`.

**Updated Plan**: `Store._ensure_fts5()` (line 170) creates a test virtual table, catches `OperationalError`, and raises a clear `RuntimeError` with platform-specific install instructions. Called at line 164 in `__init__()`.

**Verdict**: **Fixed**

**Note**: Exactly matches the R1 recommendation — test table creation with clear error message including `apt install` guidance.

---

## 6. No Console Scripts Entry Point (R1: medium)

**Finding**: R1 noted no `[project.scripts]` entry to expose `khub` as a shell command.

**Updated Plan**: `pyproject.toml` (line 65):
```toml
[project.scripts]
khub = "khub.cli:main"
```

**Verdict**: **Fixed**

---

## 7. Sync is Placeholder (R1: high)

**Finding**: R1 required implementing `sync` to actually iterate over configured sources and sync them, even if only OCR for M1.

**Updated Plan** (line 1085):
```python
if args.cmd == "sync":
    print("M1 仅支持 OCR push-in 源，请使用 `khub ingest --book <目录>` 替代 sync。"
          "其他源的 sync 功能在 M2 实现。")
```

The message is more informative than the R1 placeholder, but the command **still does not actually sync anything**. It just tells the user to use `ingest` instead. The `--source` argument is parsed but never used.

**Verdict**: **Partial**

**Note**: The message is improved (directs users to `ingest`), but the R1 recommendation was clear: "Implement the sync command to actually iterate over configured sources" and "Even for M1, the sync command should work end-to-end for the OCR adapter." This was not done. As written, `khub sync` remains a dead command.

---

## 8. No `__main__.py` (med — added in R2 scope)

**Finding**: Without `__main__.py`, `python -m khub` would fail.

**Updated Plan**: `khub/__main__.py` (line 1036):
```python
from khub.cli import main
import sys
if __name__ == "__main__":
    sys.exit(main())
```

**Verdict**: **Fixed**

**Note**: Allows `python -m khub` — also implicitly tested by CLI tests using `python -m khub.cli`.

---

## R2 Summary

| Finding | R1 Severity | Verdict |
|---------|-------------|---------|
| 1. Test/impl mismatch (click → subprocess) | high | **Fixed** |
| 2. E2E test writes to prod DB | high | **Not fixed** |
| 3. No logging | high | **Partial** |
| 4. No schema migration | high | **Not fixed** |
| 5. Runtime FTS5 check (`_ensure_fts5`) | medium | **Fixed** |
| 6. No console_scripts (`[project.scripts]`) | medium | **Fixed** |
| 7. Sync is placeholder | high | **Partial** |
| 8. No `__main__.py` | medium | **Fixed** |

### Blocking (Unresolved High Severity)

1. **E2E test writes to prod DB**: `KHUB_CONFIG` points to a non-existent file → falls back to production DB. Tests will corrupt the user's real `khub.db`. Fix: create the config YAML in the test with a `tmp_path`-based DB path, or add a CLI `--db` flag.

2. **No schema migration**: No `schema_version` table or migration path. M2+ schema changes will break existing databases.

3. **Logging (partial)**: Only 1 `logging.warning` call in `ocr.py`. Engine and CLI remain silent. No `logging.basicConfig`, no `--verbose`.

4. **Sync still a placeholder**: Command prints help text instead of actually syncing. Acceptable for M1 if `ingest` is the primary workflo, but the command is technically non-functional.
