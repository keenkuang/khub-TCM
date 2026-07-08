import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

from .api import serve
from .db import Store
from .models import CanonicalDoc
from .exam.generator import generate
from .clinical.patients import add_patient
from .clinical.records import add_record
from .clinical.consultations import add_consultation
from .clinical.twin import build_summary
from .ops.store import book_appointment
from .ingest import ingest_ebook, register_ebook
from .storage import ManagedLibrary

DEFAULT_DB = os.path.expanduser("~/.khub/khub.db")
DEFAULT_LIB = os.path.expanduser("~/.khub/library")


def build_parser():
    ap = argparse.ArgumentParser(prog="khub")
    sub = ap.add_subparsers(dest="cmd")
    pa = sub.add_parser("add", help="注册一个 PDF/EPUB 到受管库（不入库）")
    pa.add_argument("path")
    pa.add_argument("--move", action="store_true", help="移动原文件而非复制")
    sub.add_parser("list", help="列出已注册的电子书")
    pi = sub.add_parser("ingest", help="把已注册的电子书入库（抽文本+建索引）")
    pi.add_argument("canonical_id")
    ps = sub.add_parser("serve", help="启动 REST API（薄层，复用核心库）")
    ps.add_argument("--host", default="127.0.0.1")
    ps.add_argument("--port", type=int, default=8000)

    pg = sub.add_parser("exam-gen", help="根据主题生成一道中医考题")
    pg.add_argument("topic")
    pg.add_argument("--source-doc", default="", dest="source_doc")

    pp = sub.add_parser("patient-add", help="登记一名患者")
    pp.add_argument("id")
    pp.add_argument("name")
    pp.add_argument("--gender", default="")
    pp.add_argument("--born", default="")

    pr = sub.add_parser("record-add", help="为某患者添加病历记录")
    pr.add_argument("patient_id")
    pr.add_argument("--diagnosis", default="")
    pr.add_argument("--prescription", default="")
    pr.add_argument("--note", default="")

    pc = sub.add_parser("consult-add", help="为某患者添加问诊记录")
    pc.add_argument("patient_id")
    pc.add_argument("--chief", default="", dest="chief_complaint")
    pc.add_argument("--diff", default="", dest="differentiation")
    pc.add_argument("--plan", default="")

    pb = sub.add_parser("ops-book", help="为患者预约挂号")
    pb.add_argument("patient_id")
    pb.add_argument("date")
    pb.add_argument("doctor")

    pt = sub.add_parser("twin-summary", help="生成患者数字孪生摘要")
    pt.add_argument("patient_id")

    pd = sub.add_parser("doc-add", help="直接入库一份文档（KZOCR/OCR 产出，不依赖原始文件）")
    pd.add_argument("--title", required=True)
    src = pd.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="从文件读取正文（markdown 等）")
    src.add_argument("--content", help="直接传入正文")
    pd.add_argument("--source-id", default="", dest="source_id")
    pd.add_argument("--source", default="KZOCR")
    pd.add_argument("--format", default="markdown")
    pd.add_argument("--metadata", default="", help="JSON 字符串，附加元数据")

    pw = sub.add_parser("watch", help="监听目录，KZOCR 产出 .md 落盘即自动入库")
    pw.add_argument("dir")
    pw.add_argument("--interval", type=float, default=3.0, help="轮询间隔（秒）")

    pq = sub.add_parser("quip-sync", help="从 Quip 拉取文档归档到本地库")
    pq.add_argument("--token", default="", help="Quip API access_token；默认读 KHUB_QUIP_TOKEN 环境变量")
    pq.add_argument("--root", default="ROOT", help="起始文件夹 ID（默认用户根目录）")

    po = sub.add_parser("obsidian-import", help="导入 Obsidian vault（.md 目录）到本地库")
    po.add_argument("vault_path")
    po.add_argument("--no-recursive", dest="recursive", action="store_false", default=True)

    pima = sub.add_parser("ima-sync", help="与腾讯 IMA 知识库同步（双向）")
    pima.add_argument("--kb-id", default="", help="指定知识库 ID（不指定则同步全部）")
    pima.add_argument("--direction", default="pull",
                      choices=["pull", "push", "both"],
                      help="同步方向：pull=拉取 push=推送 both=双向（默认 pull）")

    pn = sub.add_parser("ima-note-sync", help="拉取 IMA 笔记到本地库")

    psc = sub.add_parser("schedule", help="运行定时调度器，按配置周期执行 khub 命令")
    psc.add_argument("--config", default=os.path.expanduser("~/.khub/tasks.yaml"),
                     help="任务配置 YAML 路径")

    pdsk = sub.add_parser("desktop", help="启动桌面 GUI（浏览器模式/Electron 套壳）")
    pdsk.add_argument("--port", type=int, default=8765, help="API 端口（默认 8765）")
    pdsk.add_argument("--electron", action="store_true",
                      help="用 Electron 原生窗口（需先 bash desktop/run.sh 安装 Electron）")

    pp = sub.add_parser("ima-probe", help="探测 IMA API 频率限制规律（持续运行）")
    pp.add_argument("--interval", type=int, default=3600,
                    help="探测间隔（秒，默认 3600=1h）")
    pp.add_argument("--once", action="store_true", help="只执行一次并退出")

    pdr = sub.add_parser("dr", help="远程灾备（DR）：本地副本 + 多版本快照 + 恢复校验（P0a）")
    dr_sub = pdr.add_subparsers(dest="dr_cmd")
    pinit = dr_sub.add_parser("init", help="配置一个灾备副本目标（建 ReplicaTarget）")
    pinit.add_argument("--target", required=True,
                       help="file:///绝对路径（本地副本，仅防误删）"
                            " 或 ssh://user@host/路径（异地灾备，防机器坏/勒索）")
    dr_sub.add_parser("verify", help="恢复前校验：integrity_check + 行数 + max(lsn) + FTS 抽样")
    dr_sub.add_parser("status", help="显示上次成功备份时间")
    ppush = dr_sub.add_parser("push", help="推送快照 + 增量 WAL 到副本目标")
    ppush.add_argument("--replica", default="",
                       help="file:// 或 ssh:// 目标；省略则用已配置的 dr_target")
    pls = dr_sub.add_parser("list-snapshots", help="列出可用快照（ts / lsn / at）")
    pls.add_argument("--replica", default="",
                     help="file:// 或 ssh:// 目标；省略则用已配置的 dr_target")
    prest = dr_sub.add_parser("restore", help="用快照 + WAL 恢复到指定时间点（PITR）")
    prest.add_argument("--to", required=True,
                       help="恢复目标：整数 lsn / @2026-01-01T00:00:00（时间）/ latest")
    prest.add_argument("--replica", default="",
                       help="file:// 或 ssh:// 目标；省略则用已配置的 dr_target")
    prest.add_argument("--target", default="",
                       help="恢复输出 db 路径（省略则用临时库并只做报告，不动原库）")
    return ap


# ── DR 辅助 ────────────────────────────────────────────────────────────────

def _dr_make_replica(target):
    """由 file:// 或 ssh:// 目标串构造 ReplicaTarget。"""
    from .replication import LocalFileReplica, SshReplica
    if target.startswith("file://"):
        return LocalFileReplica(os.path.expanduser(target[len("file://"):]))
    if target.startswith("ssh://"):
        return SshReplica(target)
    raise ValueError("target 须以 file:// 或 ssh:// 开头")


def _dr_stored_target(store):
    tgt = store.ha_get("dr_target")
    if not tgt:
        return None
    return json.loads(tgt)["target"]


def _dr_parse_restore_target(spec, changes):
    """把 --to 解析为 target_lsn（int | None）。

    - ``latest`` → None（回放全量）
    - ``@2026-01-01T00:00:00`` → WAL/快照里 ``at<=时间`` 的最大 lsn
    - 整数 → 该 lsn
    """
    if spec == "latest":
        return None
    if spec.startswith("@"):
        tstr = spec[1:]
        t = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                t = time.strptime(tstr, fmt)
                break
            except ValueError:
                continue
        if t is None:
            raise ValueError(f"无法解析恢复时间：{tstr}")
        best = None
        for c in changes:
            at = c.get("at") or ""
            try:
                ct = time.strptime(at, "%Y-%m-%dT%H:%M:%S")
            except Exception:
                continue
            if ct <= t:
                lsn = c.get("lsn") or c.get("id") or 0
                if best is None or lsn > best:
                    best = lsn
        return best
    try:
        return int(spec)
    except ValueError:
        raise ValueError(f"无法解析恢复目标：{spec}（整数 lsn / @时间 / latest）")


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = Store(os.environ.get("KHUB_DB", DEFAULT_DB))
    lib = ManagedLibrary(os.environ.get("KHUB_LIBRARY", DEFAULT_LIB))

    if args.cmd == "add":
        cid = register_ebook(store, lib, args.path, move=args.move)
        print(cid)
    elif args.cmd == "list":
        for e in store.list_ebooks():
            flag = "ingested" if e["ingested"] else "catalog"
            print(f"{e['canonical_id']}\t{e['title']}\t{e['format']}\t{flag}")
    elif args.cmd == "ingest":
        vid = ingest_ebook(store, args.canonical_id)
        print(f"{args.canonical_id} -> version {vid}")
    elif args.cmd == "serve":
        serve(store, lib, args.host, args.port)
    elif args.cmd == "exam-gen":
        q = generate(args.topic, source_doc=args.source_doc)
        print(q.stem)
    elif args.cmd == "patient-add":
        pid = add_patient(store, args.id, args.name, gender=args.gender, born=args.born)
        print(pid)
    elif args.cmd == "record-add":
        rid = add_record(store, args.patient_id, diagnosis=args.diagnosis,
                         prescription=args.prescription, note=args.note)
        print(rid)
    elif args.cmd == "consult-add":
        cid = add_consultation(store, args.patient_id, chief_complaint=args.chief_complaint,
                               differentiation=args.differentiation, plan=args.plan)
        print(cid)
    elif args.cmd == "ops-book":
        aid = book_appointment(store, args.patient_id, args.date, args.doctor)
        print(aid)
    elif args.cmd == "twin-summary":
        print(build_summary(store, args.patient_id))
    elif args.cmd == "doc-add":
        content = args.content
        if args.file:
            with open(args.file, encoding="utf-8") as f:
                content = f.read()
        metadata = json.loads(args.metadata) if args.metadata else {}
        doc = CanonicalDoc(
            canonical_id=args.source_id or f"kzocr-{int(time.time()*1000)}",
            title=args.title,
            content=content,
            source=args.source,
            source_id=args.source_id or "",
            origin="kzocr",
            format=args.format,
            note=json.dumps(metadata, ensure_ascii=False),
        )
        vid = store.store_document(doc)
        try:
            from .retrieval import Retriever
            Retriever(store).index_ebook(doc.canonical_id)
        except Exception:
            pass
        print(f"{doc.canonical_id} -> version {vid}")
    elif args.cmd == "watch":
        from .watch import watch_and_ingest
        watch_and_ingest(store, args.dir, interval=args.interval)
    elif args.cmd == "quip-sync":
        from .quip import pull_all
        token = args.token or os.environ.get("KHUB_QUIP_TOKEN", "")
        if not token:
            print("错误：需要 --token 参数或 KHUB_QUIP_TOKEN 环境变量", file=sys.stderr)
            return 1
        ingested, skipped = pull_all(store, token, args.root)
        print(f"Quip 同步完成：入库 {ingested}，跳过 {skipped}")
    elif args.cmd == "obsidian-import":
        from .obsidian import import_vault
        ingested, skipped = import_vault(store, args.vault_path, recursive=args.recursive)
        print(f"Obsidian 导入完成：入库 {ingested}，跳过 {skipped}")
    elif args.cmd == "ima-sync":
        from .sync_engine import TwoWaySyncEngine
        from .ima import sync_adapter
        engine = TwoWaySyncEngine(store)
        if args.kb_id:
            adapter = sync_adapter(store, args.kb_id)
            res = engine.sync(f"ima:{args.kb_id}", adapter,
                              direction=args.direction)
            print(f"IMA {args.kb_id[:20]}... 同步完成: "
                  f"pull {res.get('pull',{}).get('ingested',0)}"
                  f" / push {res.get('push',{}).get('pushed',0)}")
        else:
            from .ima import list_knowledge_bases
            kbs = list_knowledge_bases()
            total_pull = total_push = 0
            for kb in kbs:
                adapter = sync_adapter(store, kb["id"])
                res = engine.sync(f"ima:{kb['id']}", adapter,
                                  direction=args.direction)
                p = res.get('pull',{}).get('ingested',0)
                pu = res.get('push',{}).get('pushed',0)
                total_pull += p; total_push += pu
                print(f"  {kb['name']}: pull={p} push={pu}")
            print(f"IMA 同步完成：{len(kbs)} 个库，"
                  f"共拉取 {total_pull} / 推送 {total_push} 篇")
    elif args.cmd == "ima-note-sync":
        from .ima_notes import sync_cli
        res = sync_cli(store, verbose=True)
        total = sum(r["ingested"] for r in res)
        print(f"IMA 笔记同步完成：{total} 篇")
    elif args.cmd == "schedule":
        from .scheduler import read_tasks, run_tasks
        tasks = read_tasks(args.config)
        if not tasks:
            print(f"schedule：{args.config} 无有效任务，退出", file=sys.stderr)
            return 1
        print(f"调度器启动，{len(tasks)} 个任务")
        run_tasks(store, tasks, blocking=True)
    elif args.cmd == "desktop":
        port = args.port
        t = threading.Thread(target=serve, args=(store, lib, "127.0.0.1", port), daemon=True)
        t.start()
        time.sleep(1.5)
        url = f"http://127.0.0.1:{port}/"
        desktop_dir = os.path.join(os.path.dirname(__file__), "..", "desktop")
        if args.electron:
            print(f"启动 Electron 窗口 -> {url}")
            subprocess.Popen(["npx", "electron", "main.js"], cwd=desktop_dir,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(f"在浏览器中打开 -> {url}")
            webbrowser.open(url)
        print("按 Ctrl+C 停止服务")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n服务停止")
    elif args.cmd == "ima-probe":
        from .ima_probe import _log, _probe as _p, run_multi_endpoint
        if not os.environ.get("IMA_CLIENT_ID") or not os.environ.get("IMA_API_KEY"):
            print("错误：请设置 IMA_CLIENT_ID 和 IMA_API_KEY 环境变量", file=sys.stderr)
            return 1
        if args.once:
            r = _p()
            _log(r, os.path.expanduser("~/.khub/ima_probe.jsonl"))
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            run_multi_endpoint()
    elif args.cmd == "dr":
        from .replication import (LocalFileReplica, SshReplica, ReplicationManager,
                                   verify_store, replay_from)
        from .db import rebuild_fts
        import shutil as _shutil
        import socket

        if args.dr_cmd == "init":
            target = args.target
            if target.startswith("file://"):
                path = os.path.expanduser(target[len("file://"):])
                replica = LocalFileReplica(path)
                kind = "本地副本"
            elif target.startswith("ssh://"):
                replica = SshReplica(target)
                kind = "异地灾备"
            else:
                print("错误：--target 须以 file:// 或 ssh:// 开头", file=sys.stderr)
                return 1
            store.ha_set("dr_target", json.dumps({"type": kind, "target": target}))
            try:
                ReplicationManager(store).push_snapshot(replica, db_path=store.path)
            except Exception as e:
                print(f"警告：初始快照推送失败（{e}）；目标已记录。",
                      file=sys.stderr)
            if kind == "本地副本":
                print(f"已配置【本地副本】目标：{target}")
                print(f"注意：此副本与知识库同在 {socket.gethostname()}，"
                      f"仅防误删/改坏，不算异地灾备；"
                      f"防勒索/机器坏请改用 ssh:// 异地副本。")
            else:
                print(f"已配置【异地灾备】目标：{target}")
                print("SshReplica 已就绪（配通 SSH 免密后即具备异地保护）；"
                      "建议每季做一次恢复演练。")
        elif args.dr_cmd == "verify":
            report = verify_store(store)
            print("=== khub dr verify ===")
            print(f"integrity_check : {report['integrity']}")
            print(f"max(lsn)        : {report['max_lsn']}")
            print(f"docs_fts 抽样   : {report['fts_sample']}")
            print("行数：")
            for t, n in report["row_counts"].items():
                if n >= 0:
                    print(f"  {t:14s}: {n}")
            if report["ok"]:
                print("结果：通过")
                return 0
            print("结果：失败")
            for e in report["errors"]:
                print(f"  - {e}")
            return 1
        elif args.dr_cmd == "status":
            tgt = store.ha_get("dr_target")
            if not tgt:
                print("尚未配置灾备目标，请先 `khub dr init --target ...`",
                      file=sys.stderr)
                return 1
            info = json.loads(tgt)
            meta = None
            if info["target"].startswith("file://"):
                try:
                    rep = LocalFileReplica(
                        os.path.expanduser(info["target"][len("file://"):]))
                    meta = rep.fetch_snapshot()
                except Exception:
                    pass
            print(f"目标类型：{info['type']}")
            print(f"目标地址：{info['target']}")
            print(f"上次成功备份：{meta.get('at') if meta else '无（尚未推送过快照）'}")
        elif args.dr_cmd == "push":
            target = args.replica or _dr_stored_target(store)
            if not target:
                print("错误：未指定 --replica 且尚未配置 dr_target；"
                      "请先 `khub dr init --target ...` 或传 --replica",
                      file=sys.stderr)
                return 1
            replica = _dr_make_replica(target)
            mgr = ReplicationManager(store)
            meta = mgr.push_snapshot(replica, db_path=store.path)
            n = mgr.push_pending(replica)
            print(f"已推送快照（lsn={meta.get('max_replication_id')}）"
                  f"与 {n} 条增量 WAL 到 {replica.name}")
            if target.startswith("file://"):
                print("提示：此副本与知识库同机，仅防误删/改坏；"
                      "防机器坏/勒索请改用 ssh:// 异地副本。")
        elif args.dr_cmd == "list-snapshots":
            target = args.replica or _dr_stored_target(store)
            if not target:
                print("错误：未指定 --replica 且尚未配置 dr_target；"
                      "请先 `khub dr init --target ...` 或传 --replica",
                      file=sys.stderr)
                return 1
            replica = _dr_make_replica(target)
            if isinstance(replica, SshReplica):
                versions = replica.list_remote_versions()
            else:
                versions = replica.list_versions()
            if not versions:
                print(f"无可用快照（{replica.name}）")
                return 0
            print(f"副本 {replica.name} 的快照（按时间升序）：")
            for v in versions:
                print(f"  ts={v['ts']:<17} lsn={v['lsn']:<8} at={v['at']}")
        elif args.dr_cmd == "restore":
            target = args.replica or _dr_stored_target(store)
            if not target:
                print("错误：未指定 --replica 且尚未配置 dr_target；"
                      "请先 `khub dr init --target ...` 或传 --replica",
                      file=sys.stderr)
                return 1
            replica = _dr_make_replica(target)
            # 拉取全量 WAL（含 lsn/at）用于目标解析与回放
            changes = replica.fetch_changes() or []
            try:
                target_lsn = _dr_parse_restore_target(args.to, changes)
            except ValueError as e:
                print(f"错误：{e}", file=sys.stderr)
                return 1
            # 选取 lsn<=target 的最近快照
            if isinstance(replica, SshReplica):
                versions = replica.list_remote_versions()
                cands = (versions if target_lsn is None
                         else [v for v in versions if v["lsn"] <= target_lsn])
                snap = cands[-1] if cands else None
                if snap is None:
                    print("错误：无满足目标时间点的远端快照（需更早的快照）",
                          file=sys.stderr)
                    return 1
                snap_db = replica.fetch_remote_snapshot_db(snap["ts"])
                snapshot_lsn = snap["lsn"]
                snapshot_at = snap["at"]
            else:
                snap = replica.best_snapshot_for(target_lsn)
                if snap is None:
                    print("错误：无满足目标时间点的本地快照（需更早的快照）",
                          file=sys.stderr)
                    return 1
                snap_db = snap["db"]
                snapshot_lsn = snap["lsn"]
                snapshot_at = snap["at"]
            # 拷到 --target（默认临时库），以 Store 打开并重建 FTS（不动原库）
            out_db = args.target or tempfile.mktemp(suffix=".db")
            _shutil.copy(snap_db, out_db)
            restored = Store(out_db)
            rebuild_fts(restored)
            restored.set_applied_max(snapshot_lsn)
            applied = replay_from(restored, changes, target_lsn=target_lsn)
            recovered_lsn = restored.applied_max()
            n_docs = restored.conn.execute(
                "SELECT COUNT(*) FROM documents").fetchone()[0]
            vrep = verify_store(restored)
            print(f"已从 {replica.name} 恢复")
            print(f"  快照 lsn   : {snapshot_lsn}  (at {snapshot_at})")
            print(f"  恢复目标   : {args.to} -> lsn={target_lsn}")
            print(f"  本批回放   : {applied} 条")
            print(f"  恢复 lsn   : {recovered_lsn}")
            print(f"  documents  : {n_docs} 行")
            print(f"  integrity  : {vrep['integrity']}")
            print(f"  结果       : {'通过' if vrep['ok'] else '失败（见下方）'}")
            for e in vrep["errors"]:
                print(f"    - {e}")
            if not args.target:
                try:
                    os.remove(out_db)
                except OSError:
                    pass
                print("（默认已用临时库校验，未改动任何已有库；"
                      "如需落盘请加 --target <out.db>）")
            return 0 if vrep["ok"] else 1
        else:
            pdr.print_help()
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
