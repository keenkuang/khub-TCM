# Operations Review: khub M1

- **Reviewer**: CodeBuddy (ops review agent)
- **Date**: 2026-07-09
- **Reviewed artifacts**:
  - `/home/keen/khub/docs/superpowers/specs/2026-07-07-khub-design.md`
  - `/home/keen/khub/docs/superpowers/plans/2026-07-07-khub-m1.md`

---

## 1. Dependencies

- **Finding**: PyYAML `>=6.0` is specified, which is correct for Python 3.11. However, PyYAML 6.0.0/6.0.1 do not ship official wheels for Python 3.13+ on some platforms (e.g. Windows arm64, Linux aarch64 via `pip` may require a source build with a C compiler). Python 3.11–3.12 are safe.
- **Severity**: low
- **Recommendation**: Pin to `PyYAML>=6.0,<7` and note that the user will need a C compiler on Python 3.13 if no wheel is available. Alternatively, consider `ruamel.yaml` or using the stdlib `tomllib` for config (if willing to switch to TOML), but YAML is fine for this use case.

- **Finding**: The test file `tests/test_cli.py` (Task 9, Steps 1–2) imports `click.testing.CliRunner` and `khub.cli.cli`, but the implemented CLI uses `argparse` only. `click` is never added to `pyproject.toml` dependencies. The tests will fail with `ModuleNotFoundError` for `click`.
- **Severity**: high
- **Recommendation**: Align tests with the actual `argparse` implementation. Use `subprocess.run([sys.executable, "-m", "khub.cli", ...])` for CLI tests, as noted in the plan's own commentary. Remove all `click` imports from test files.

- **Finding**: The plan adds `click` to `pyproject.toml` in Task 9 Step 3 commentary but the final implementation uses `argparse`. The pyproject.toml excerpt in Task 1 lists only `PyYAML>=6.0` and `pytest>=8.0`. No `click` is listed - consistent with argparse usage, but the test code is out of sync.
- **Severity**: medium
- **Recommendation**: Ensure `tests/test_cli.py` does not reference `click.testing.CliRunner`. Finalize the dependency list before implementation.

---

## 2. Deployment

- **Finding**: Installation is via `pip install .` (editable). There is no `[project.scripts]` entry in `pyproject.toml` to expose `khub` as a shell command. The plan relies on `python -m khub.cli` or `python -m khub.cli`. After `pip install -e .`, `khub` won't be on `$PATH` unless a console_scripts entry point is defined.
- **Severity**: medium
- **Recommendation**: Add a console_scripts entry point to `pyproject.toml`:
  ```toml
  [project.scripts]
  khub = "khub.cli:main"
  ```
  This makes `khub` available as a regular command after `pip install`.

- **Finding**: FTS5 availability is checked via a pytest test (`test_fts5_available` in `conftest.py`), which is a good pattern. However, this check only runs when tests are executed, not at install time or first CLI invocation. A user installing khub without running tests will get a runtime failure when FTS5 queries are attempted.
- **Severity**: medium
- **Recommendation**: Add a runtime FTS5 check in `Store.__init__()` (or a separate `verify_environment()` function called by CLI `main`), so the user gets a clear error immediately — not deep in a query. Example:
  ```python
  try:
      conn.execute("CREATE VIRTUAL TABLE _khub_fts_test USING fts5(x)")
      conn.execute("DROP TABLE _khub_fts_test")
  except sqlite3.OperationalError:
      raise RuntimeError("SQLite FTS5 not available; khub requires FTS5. "
                         "Install libsqlite3-mod-fts5 or use a Python build with FTS5 enabled.")
  ```

- **Finding**: No system dependencies are documented. SQLite FTS5 is not always available in the system Python's `sqlite3` module. On Ubuntu/Debian, `libsqlite3-mod-fts5` may need to be installed; on macOS, the system Python may be fine but Homebrew Python sometimes ships without FTS5.
- **Severity**: low
- **Recommendation**: Document system requirements in a `README.md` or `INSTALL.md`: "Requires Python 3.11+ with FTS5 support in sqlite3. On Ubuntu: `apt install libsqlite3-mod-fts5`."

---

## 3. Configuration Management

- **Finding**: The config path is hardcoded to `/home/keen/khub/config.yaml` with an override via `KHUB_CONFIG` env var. This is acceptable for personal use but creates a tight coupling to the user's home directory structure. Sharing the project or running from a different machine requires changes.
- **Severity**: low
- **Recommendation**: Acceptable for M1 (personal use). For M2+, consider a `--config` CLI flag or `khub init` command that creates config in `~/.config/khub/config.yaml` with XDG convention.

- **Finding**: The `_store()` function in `cli.py` silently falls back to defaults when `KHUB_CONFIG=""` or the config file does not exist:
  ```python
  cfg = load_config(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else {"db": "/home/keen/khub/khub.db"}
  ```
  This means a missing config file is never reported, and the DB path is silently set to a default. If a user removes `config.yaml` intentionally or accidentally, the system continues with a potentially wrong DB path.
- **Severity**: medium
- **Recommendation**: Emit a warning when falling back to default config:
  ```python
  if not os.path.exists(CONFIG_PATH):
      import logging
      logging.warning("config.yaml not found at %s; using default db path", CONFIG_PATH)
  ```

- **Finding**: The `config.secret()` function returns an empty string by default when an env var is not set, with no error or warning. A missing `IMA_TOKEN` or `QUIP_TOKEN` will manifest as a confusing authentication failure at sync time, not a clear configuration error.
- **Severity**: medium
- **Recommendation**: Either add a `required=True` parameter to `secret()` that raises `ConfigError` if the variable is unset, or validate all expected env vars at startup in the CLI `main()`.

---

## 4. Logging & Observability

- **Finding**: The plan has zero logging calls. All output goes to `print()` in the CLI. There is no `import logging`, no structured logging, no log levels, no log rotation, and no way to debug failures without re-running with `print()` statements. Specifically:
  - `engine.py` silently skips unchanged documents (line 649: `continue`).
  - Adapter failures are not logged (design spec promises "single source failure isolation", but the plan never implements error capture and logging).
  - No timestamps or performance metrics (how long did a sync take? How many documents were processed?).
- **Severity**: high
- **Recommendation**: Add `import logging` with a `__init__.py`-level logger. At minimum:
  - Log sync start/end with document count and duration.
  - Log `info` for created/updated/conflict events.
  - Log `warning` for skipped documents or adapter errors.
  - Log `error` for adapter exceptions (with traceback).
  - Use `logging.basicConfig(level=logging.INFO)` in CLI `main()`.
  - Consider `--verbose`/`-v` flag to enable `DEBUG` level.

- **Finding**: The CLI only uses `print()` for user-facing output. This means stdout mixes "business results" (e.g. query output) with status messages. When the CLI is used in cron or piped to other commands, status lines like "sync 完成" will contaminate structured output.
- **Severity**: medium
- **Recommendation**: Use `print()` only for command results (query output, conflict list). Use `logging` or `stderr` for status/progress messages. This makes the CLI cron-friendly and scriptable.

---

## 5. Error Recovery

- **Finding**: There is no backup strategy for the SQLite database. If `khub.db` is corrupted (power loss, filesystem error, bug), all data is lost. The design's core promise is "不丢任何内容" (never lose content), but the plan has no mechanism to uphold this promise at the storage layer.
- **Severity**: high
- **Recommendation**: Implement at minimum:
  1. **SQLite PRAGMA integrity_check** — run on startup, warn if corrupted.
  2. **Automatic backup** — before each sync, copy the DB file to `khub.db.backup` (or `khub.db.<date>`). For SQLite, use the `backup()` API rather than `shutil.copy` to ensure consistency.
  3. **Add a `khub backup` CLI command** for manual backups.
  4. Document that users should set up periodic filesystem-level backups (e.g. `rsync` / `restic`).

- **Finding**: SQLite uses rollback journal mode by default. No `PRAGMA journal_mode=WAL` is set. This means:
  - Reads block writes and writes block reads.
  - Crash recovery is handled by the journal, but corruption is more likely under power loss compared to WAL mode.
- **Severity**: medium
- **Recommendation**: Set `PRAGMA journal_mode=WAL` in `Store.__init__()` for better concurrent read performance and crash safety. WAL is well-tested and appropriate for this use case.

- **Finding**: The `e2e smoke test` (Task 10) sets `KHUB_CONFIG=""`, which triggers the fallback default DB path. This means the test writes to `/home/keen/khub/khub.db` during testing — potentially overwriting the user's real database.
- **Severity**: high
- **Recommendation**: The e2e test must use an isolated temp DB path. Either pass a `--db` flag to the CLI, or set `KHUB_CONFIG` to a temp yaml that overrides `db`. Never let tests touch the production DB path.

---

## 6. Platform Compatibility

- **Finding**: `requires-python = ">=3.11"` is specified. All code uses stdlib only (plus PyYAML). The code appears compatible with Python 3.11–3.13, with the caveat about PyYAML wheels noted in section 1.
- **Severity**: info
- **Recommendation**: Test on at least one version in each minor range (3.11, 3.12, 3.13) in CI. Add a `python_requires` classifier to `pyproject.toml`.

- **Finding**: Hardcoded POSIX paths (`/home/keen/khub/khub.db`, `/home/keen/khub/config.yaml`, `/home/keen/khub/inbox/ocr`) make the project non-portable to Windows or macOS out of the box. The `pathlib` usage is good, but the hardcoded defaults in `cli.py` are Linux-specific.
- **Severity**: low
- **Recommendation**: For M1 this is acceptable (personal tool). For future releases, use platform-appropriate defaults:
  - Linux: `~/.config/khub/`
  - macOS: `~/Library/Application Support/khub/`
  - Windows: `%APPDATA%/khub/`

- **Finding**: SQLite FTS5 availability is inconsistent across platforms and Python distributions. The standard `sqlite3` module on Windows (official Python builds) may include FTS5, but on Linux it depends on the system `libsqlite3`. Alpine Linux (musl) often lacks FTS5 entirely.
- **Severity**: medium
- **Recommendation**: Document known platform FTS5 issues. Consider a graceful fallback: if FTS5 is unavailable, fall back to `LIKE '%keyword%'` or Python-level search (for M1, acceptable; for M2+ FTS5 is needed for performance).

---

## 7. Database Lifecycle

- **Finding**: No schema migration strategy exists. The schema uses `CREATE TABLE IF NOT EXISTS` exclusively. When new columns or tables are added in M2+ (e.g., `embeddings` is already created in M1), existing databases will not be altered. Adding columns to existing tables requires ALTER TABLE, which is not handled.
- **Severity**: high
- **Recommendation**: Implement a minimal schema versioning system:
  1. Add a `schema_version` table:
     ```sql
     CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
     INSERT INTO schema_version (version) VALUES (1);
     ```
  2. In `Store.__init__()`, check the current version against the expected version and run migration functions for each version gap.
  3. For M1, this is version 1. Future M-steps increment the version and add migration logic.

- **Finding**: There is no `VACUUM` strategy. Over time, as documents are updated and old versions accumulate, the database file will grow without bound. Old versions are never pruned.
- **Severity**: low
- **Recommendation**: Document that `sqlite3` will not automatically reclaim space. Consider adding a `khub vacuum` command or a periodic maintenance routine (M3+ with scheduler). For M1, accept unbounded growth; user can manually run `VACUUM`.

---

## 8. Performance

- **Finding**: No `PRAGMA journal_mode=WAL` is set (as noted in section 5). For M1 with only CLI access (serial operations), this is acceptable. For M2 when Web UI is added (concurrent reads from browser + writes from sync), the default rollback journal will cause `SQLITE_BUSY` errors during sync when the Web UI is querying.
- **Severity**: medium
- **Recommendation**: Enable WAL mode in `Store.__init__()` now to avoid a migration surprise in M2:
  ```python
  self.conn.execute("PRAGMA journal_mode=WAL")
  self.conn.execute("PRAGMA busy_timeout=5000")
  ```
  Also set `busy_timeout` to avoid immediate `SQLITE_BUSY` failures.

- **Finding**: The `sync_source` method in `engine.py` processes documents one by one in a loop with individual SQL commits. For large syncs (e.g., Quip with thousands of documents), this will be slow.
- **Severity**: info
- **Recommendation**: Acceptable for M1. For M2+ large syncs, consider batching documents within a single transaction.

---

## 9. Cron / Automation

- **Finding**: The CLI is suitable for cron-based scheduled sync. The `khub sync` command is a single-shot operation that reads config and syncs. However:
  - The `sync` subcommand currently only prints a placeholder message: `"sync 完成（M1 仅支持 ocr 源）"`. It does not actually iterate over configured sources.
  - There is no `--source` filter implementation in the `main()` function.
  - The `--source` argument is parsed but never read.
- **Severity**: high
- **Recommendation**: Implement the sync command to actually iterate over configured sources:
  ```python
  if args.cmd == "sync":
      cfg = load_config(...)
      for src_cfg in cfg.get("sources", []):
          if args.source and src_cfg["name"] != args.source:
              continue
          adapter = _build_adapter(src_cfg)
          if adapter:
              eng.sync_source(adapter)
  ```
  Even for M1, the sync command should work end-to-end for the OCR adapter.

- **Finding**: No lock mechanism is mentioned. If a cron job fires while a previous sync is still running, two processes will write to the same DB file. With `PRAGMA busy_timeout`, one will wait; without it, one will get `SQLITE_BUSY` and fail. Neither is ideal.
- **Severity**: medium
- **Recommendation**: Implement a simple file lock (e.g. `fcntl.flock` on Linux, `msvcrt` on Windows) or use SQLite's own locking. At minimum, set `PRAGMA busy_timeout=10000` so concurrent syncs wait gracefully. For M2+, consider a PID file in `/tmp/khub.pid`.

- **Finding**: The `_store()` function loads config and opens a new DB connection on every CLI invocation. This is correct and expected for cron (no daemon process), but it means config is re-read each time, which is good for cron reliability.
- **Severity**: info
- **Recommendation**: No change needed. This pattern is correct for cron-based usage.

---

## Summary

| Section | High | Medium | Low | Info |
|---------|------|--------|-----|------|
| 1. Dependencies | 1 | 1 | 1 | 0 |
| 2. Deployment | 0 | 2 | 1 | 0 |
| 3. Configuration | 0 | 3 | 1 | 0 |
| 4. Logging | 1 | 1 | 0 | 0 |
| 5. Error Recovery | 2 | 1 | 0 | 0 |
| 6. Platform | 0 | 1 | 1 | 1 |
| 7. DB Lifecycle | 1 | 0 | 1 | 0 |
| 8. Performance | 0 | 1 | 0 | 1 |
| 9. Cron/Automation | 1 | 1 | 0 | 1 |
| **Total** | **6** | **11** | **5** | **3** |

### Top 3 Must-Fix Before M1 Ships

1. **DB corruption risk**: Implement SQLite backup (`khub backup` / pre-sync-auto-backup) and integrity check on startup. The design promises "never lose data" — this is the most critical gap. (high, #5)

2. **CLI test writes to production DB**: The smoke test in Task 10 writes to `/home/keen/khub/khub.db` when `KHUB_CONFIG=""`. Fix to use an isolated temp path. (high, #5)

3. **No logging**: Add `logging` throughout the engine and CLI. Operational debugging is nearly impossible with only `print()`. (high, #4)

### Additional Quick Wins (Pre-M1)

- Enable WAL mode and busy timeout in `Store.__init__()` (medium, #8, also addresses #5).
- Fix `click`-based test code to match argparse implementation (high, #1).
- Add `schema_version` table for future migrations (high, #7).
- Implement `sync` command to actually iterate over sources instead of printing a placeholder (high, #9).
- Add console_scripts entry point so `khub` works as a shell command (medium, #2).
