import argparse
import json
import os
import time

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
    return ap


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
        print(f"khub API on http://{args.host}:{args.port}")
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
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
