import argparse
import os

from .api import serve
from .db import Store
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
    else:
        build_parser().print_help()
