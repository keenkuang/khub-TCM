import argparse
import json
import os
import re
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

    pla = sub.add_parser("login", help="登录 kHUB")
    pla.add_argument("username", nargs="?", default="")
    pla.add_argument("--server", default="http://127.0.0.1:8765", help="服务器地址")

    plo = sub.add_parser("logout", help="注销当前用户")

    pw = sub.add_parser("whoami", help="显示当前用户")

    pq = sub.add_parser("query", help="全文检索本地知识库")
    pq.add_argument("keywords", nargs="+")

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

    po = sub.add_parser("ops-list", help="列出预约")
    po.add_argument("--date", default="")
    po.add_argument("--doctor", default="")
    po.add_argument("--status", default="")

    pc = sub.add_parser("ops-cancel", help="取消预约")
    pc.add_argument("appointment_id", type=int)

    pr = sub.add_parser("ops-reschedule", help="改约")
    pr.add_argument("appointment_id", type=int)
    pr.add_argument("new_date")

    ps = sub.add_parser("ops-schedule", help="新建排班")
    ps.add_argument("date"); ps.add_argument("doctor"); ps.add_argument("slot")

    pt = sub.add_parser("twin-summary", help="生成患者数字孪生摘要")
    pt.add_argument("patient_id")

    ptwin = sub.add_parser("twin", help="患者数字孪生操作（摘要刷新等）")
    twin_sub = ptwin.add_subparsers(dest="twin_cmd")
    prefresh = twin_sub.add_parser("refresh", help="增量刷新患者数字孪生摘要")
    prefresh.add_argument("twin_arg", help="患者 ID")
    prefresh.add_argument("--full", action="store_true", help="全量重建（非增量）")

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

    pfs = sub.add_parser("feishu-sync", help="拉取飞书知识空间文档入库")
    pfs.add_argument("--space-id", default="",
                     help="指定知识空间 ID（不指定则遍历所有可访问空间）")

    pi = sub.add_parser("import-legacy", help="导入老问诊系统数据（Excel/HTML）")
    pi.add_argument("--file", required=True, help="Excel .xlsx 或 HTML 文件路径")
    pi.add_argument("--sheet", default="0",
                    help='工作表名或索引（Excel，默认 0=第一张表）')
    pi.add_argument("--dry-run", action="store_true",
                    help="仅解析不写入，预览导入结果")

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
    pprune = dr_sub.add_parser(
        "prune", help="按归档窗口清理已推送(applied=1)的旧 WAL，防磁盘膨胀（I5）")
    pprune.add_argument("--keep", type=int, default=None,
                        help="本地保留最近 N 条已推送 WAL（覆盖 KHUB_WAL_KEEP）")
    pprune.add_argument("--keep-days", type=float, default=None,
                        help="保留最近 D 天内的已推送 WAL（覆盖 KHUB_WAL_KEEP_DAYS）")

    # ── 双机热备（P1） ─────────────────────────────────────────────────────
    pha = sub.add_parser(
        "ha", help="双机热备（HA）：心跳双故障域 + 写租约 + WAL 连续回放 + 故障切换（P1）")
    pha.add_argument("--manual", action="store_true",
                     help="仅检测+告警，不自动提升（恢复设计 §4.3 默认）")
    ha_sub = pha.add_subparsers(dest="ha_cmd")
    ha_sub.add_parser("status",
                      help="角色/最后同步/对端失联时长/safe mode/建议动作")
    pconf = ha_sub.add_parser("config",
                              help="配置对端 replica 目标（ssh:// 或 s3://）")
    pconf.add_argument("--peer", required=True,
                       help="ssh://user@host/路径 或 s3://bucket/前缀"
                            "（指向对端 replica 目录，供 standby 拉 WAL）")
    ha_sub.add_parser("promote", help="人工提升为本节点新主（--manual 模式用）")
    ha_sub.add_parser("demote", help="人工降级为备（停写）")
    prun = ha_sub.add_parser("run",
                             help="启动 HA 守护循环（持续回放 WAL + tick 决策）")
    prun.add_argument("--interval", type=float, default=5.0,
                      help="tick 间隔秒（默认 5）")
    prec = ha_sub.add_parser(
        "reconcile", help="分歧检测：比对双机 replication_log 输出分叉报告")
    prec.add_argument("--left", required=True,
                      help="左库 db 路径（通常为主/新主）")
    prec.add_argument("--right", required=True,
                      help="右库 db 路径（通常为备/旧主）")
    pres = ha_sub.add_parser(
        "resolve", help="safe_mode 显式退出：选定权威主后开新 epoch、定主")
    pres.add_argument("--keep", required=True,
                      choices=["primary", "standby"],
                      help="以哪一侧为权威主（primary=保持主身份，standby=切换为新主）")
    pst = ha_sub.add_parser(
        "self-test", help="HA 自我演练：注入场景运行状态机验证")
    pst.add_argument("--scenario", default="all",
                     choices=["all", "link-down", "promote", "split-brain"],
                     help="运行指定场景（默认 all 跑全部）")
    pdri = ha_sub.add_parser(
        "drill", help="端到端双节点 failover 演练（建临时双库+共享副本，跑完整生命周期）")
    pdri.add_argument("--docs", type=int, default=5,
                      help="稳态阶段主库写入文档数（默认 5）")
    pdri.add_argument("--manual", action="store_true",
                      help="以 --manual 模式演练（双域丢失仅检测+告警，不自动提升）")

    # ── 问诊助手（T3） ──────────────────────────────────────────────────
    pc = sub.add_parser("consult-chat", help="问诊助手对话")
    pc.add_argument("patient_id", type=int)
    pc.add_argument("--message", default="", help="单次消息（默认交互模式）")

    # ── 随访管理（T4） ──────────────────────────────────────────────────
    pf = sub.add_parser("followup-add", help="添加随访计划")
    pf.add_argument("pid", type=int)
    pf.add_argument("--due", required=True)
    pf.add_argument("--reason", default="")

    ps = sub.add_parser("followup-scan", help="扫描到期随访")
    ps.add_argument("--as-of", default="")

    pa = sub.add_parser("followup-adherence", help="记录随访依从性")
    pa.add_argument("plan_id", type=int)
    pa.add_argument("--attended", action="store_true")
    pa.add_argument("--missed", action="store_true")
    pa.add_argument("--note", default="")

    # ── 结构化抽取（T5） ──────────────────────────────────────────────────
    pr = sub.add_parser("record-extract", help="抽取病历结构化字段")
    pr.add_argument("record_id", type=int)

    pc = sub.add_parser("consult-extract", help="抽取问诊结构化字段")
    pc.add_argument("consult_id", type=int)

    # ── 0.2.10 课程运营管理系统 ────────────────────────────────────────
    pc = sub.add_parser("course-create", help="创建课程")
    pc.add_argument("name"); pc.add_argument("--teacher", default="")
    pc.add_argument("--desc", dest="description", default="")
    pc.add_argument("--start", dest="start_date", default="")
    pc.add_argument("--end", dest="end_date", default="")
    pc.add_argument("--capacity", type=int, default=0)
    pc.add_argument("--price", type=float, default=0)

    pcl = sub.add_parser("course-list", help="课程列表")
    pcl.add_argument("--status", default="")

    pci = sub.add_parser("course-info", help="课程详情")
    pci.add_argument("course_id", type=int)

    pla = sub.add_parser("lesson-add", help="添加课时")
    pla.add_argument("course_id", type=int); pla.add_argument("title"); pla.add_argument("date")
    pla.add_argument("--start-time", default=""); pla.add_argument("--end-time", default="")
    pla.add_argument("--location", default="")

    pll = sub.add_parser("lesson-list", help="课时列表")
    pll.add_argument("course_id", type=int)

    pe = sub.add_parser("enroll", help="学员报名")
    pe.add_argument("course_id", type=int); pe.add_argument("student_name")
    pe.add_argument("--phone", default="")

    pg = sub.add_parser("grade", help="录入成绩")
    pg.add_argument("enrollment_id", type=int); pg.add_argument("score", type=float)
    pg.add_argument("--lesson", type=int, default=0); pg.add_argument("--comment", default="")

    # 0.2.11 微信公众号
    pw = sub.add_parser("wechat-article-add", help="创建微信文章")
    pw.add_argument("--title", required=True); pw.add_argument("--content", required=True)
    pw.add_argument("--author", default=""); pw.add_argument("--digest", default="")

    pwl = sub.add_parser("wechat-article-list", help="列出文章")
    pwl.add_argument("--status", default="")

    pws = sub.add_parser("wechat-schedule", help="排期发布")
    pws.add_argument("article_id", type=int); pws.add_argument("publish_at")

    pwp = sub.add_parser("wechat-publish", help="发布到期文章")
    pwp.add_argument("--due", action="store_true", help="扫描到期排期并发布")

    pwf = sub.add_parser("wechat-sync-followers", help="同步粉丝数据")

    pul = sub.add_parser("user-list", help="列出用户")
    puc = sub.add_parser("user-create", help="创建用户")
    puc.add_argument("username"); puc.add_argument("password")
    puc.add_argument("--role", default="user"); puc.add_argument("--display", default="")
    pur = sub.add_parser("user-role", help="修改用户角色")
    pur.add_argument("user_id", type=int); pur.add_argument("role")

    # 0.4.0 clinical intelligence
    pcm = sub.add_parser("clinical-matrix", help="证型→方剂关联矩阵")
    pcm.add_argument("patient_id", type=int)

    pct = sub.add_parser("clinical-trends", help="健康趋势")
    pct.add_argument("patient_id", type=int)

    pcs = sub.add_parser("clinical-suggest", help="方剂推荐")
    pcs.add_argument("syndrome")

    pck = sub.add_parser("clinical-tracking", help="疗效评估")
    pck.add_argument("patient_id", type=int)

    # 0.5.0 knowledge graph
    pki = sub.add_parser("kg-infer", help="证型推理")
    pki.add_argument("syndrome")
    pkh = sub.add_parser("kg-herbs", help="中药查询")
    pkh.add_argument("--channel", default=""); pkh.add_argument("--nature", default="")
    pkf = sub.add_parser("kg-formulas", help="方剂列表")
    pkf.add_argument("--category", default="")
    pks = sub.add_parser("kg-similarity", help="方剂相似度")
    pks.add_argument("f1"); pks.add_argument("f2")

    # 0.6.0 开放平台
    ppl = sub.add_parser("plugin-list", help="列出已加载的插件")
    pwh = sub.add_parser("webhook-add", help="添加 Webhook 订阅")
    pwh.add_argument("--event", required=True)
    pwh.add_argument("--url", required=True)
    pwh.add_argument("--secret", default="")
    pwl = sub.add_parser("webhook-list", help="列出 Webhook 订阅")

    # 0.6.1 notifications
    pn = sub.add_parser("notify-list", help="列出通知")
    pn.add_argument("user_id", type=int)

    return ap


# ── DR 辅助 ────────────────────────────────────────────────────────────────

def _dr_make_replica(target):
    """由 file:// 或 ssh:// 目标串构造 ReplicaTarget。委托 replication.make_replica。"""
    from .replication import make_replica
    return make_replica(target)


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
            except Exception:  # nosec B112
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
    elif args.cmd == "login":
        import getpass
        username = args.username or input("用户名: ").strip()
        password = getpass.getpass("密码: ")
        server = args.server
        import urllib.request, json
        req = urllib.request.Request(f"{server}/auth/login",
                                     data=json.dumps({"username": username, "password": password}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            cred_dir = os.path.expanduser("~/.khub")
            os.makedirs(cred_dir, exist_ok=True)
            with open(os.path.join(cred_dir, "credentials"), "w") as f:
                f.write(f"KHUB_TOKEN={data['token']}\nKHUB_USER={username}\n")
            os.chmod(os.path.join(cred_dir, "credentials"), 0o600)
            print(f"登录成功！欢迎 {data.get('user', {}).get('display_name', username)}")
        except urllib.error.HTTPError as e:
            print(f"登录失败：{e.code} {e.read().decode()}")
        except Exception as e:
            print(f"连接失败：{e}")
    elif args.cmd == "logout":
        token = ""
        try:
            with open(os.path.expanduser("~/.khub/credentials")) as f:
                for line in f:
                    if line.startswith("KHUB_TOKEN="):
                        token = line.split("=", 1)[1].strip()
        except Exception: pass
        if token:
            import urllib.request, json
            try:
                req = urllib.request.Request(f"http://127.0.0.1:8765/auth/logout",
                                             data=b"{}", headers={"Content-Type": "application/json",
                                                                  "Authorization": f"Bearer {token}"})
                urllib.request.urlopen(req, timeout=5)
            except Exception: pass
        cred_file = os.path.expanduser("~/.khub/credentials")
        if os.path.isfile(cred_file):
            os.remove(cred_file)
        print("已注销")
    elif args.cmd == "whoami":
        # 简单读取本地凭证
        username = os.environ.get("KHUB_USER", "")
        token = os.environ.get("KHUB_TOKEN", "")
        if not token:
            try:
                with open(os.path.expanduser("~/.khub/credentials")) as f:
                    for line in f:
                        if line.startswith("KHUB_USER="): username = line.split("=",1)[1].strip()
                        if line.startswith("KHUB_TOKEN="): token = line.split("=",1)[1].strip()
            except Exception: pass
        if token:
            print(f"当前用户：{username or '(未知)'}")
        else:
            print("未登录。使用 `khub login` 登录")
    elif args.cmd == "serve":
        serve(store, lib, args.host, args.port)
    elif args.cmd == "query":
        q = " ".join(args.keywords)
        hits, total = store.search(q)
        for doc_id, title, snip in hits:
            print(f"{doc_id}\t{title}")
            if snip:
                print(f"  {snip}")
        if not hits:
            print(f"无结果（共 {total} 篇文档）")
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
    elif args.cmd == "ops-list":
        from .ops.store import list_appointments
        apts = list_appointments(store, date=args.date or None)
        print(f"预约：{len(apts)} 条")
        for a in apts:
            print(f"  #{a['id']} 患者{a['patient_id']} {a['date']} {a['doctor']} [{a['status']}]")
    elif args.cmd == "ops-cancel":
        from .ops.store import cancel_appointment
        cancel_appointment(store, args.appointment_id)
        print(f"预约 #{args.appointment_id} 已取消")
    elif args.cmd == "ops-reschedule":
        from .ops.store import reschedule_appointment
        new_id = reschedule_appointment(store, args.appointment_id, args.new_date)
        print(f"已改约：原 #{args.appointment_id} → 新预约 #{new_id}")
    elif args.cmd == "ops-schedule":
        from .ops.store import add_schedule
        try:
            sid = add_schedule(store, args.date, args.doctor, args.slot)
            print(f"排班 #{sid} 已创建")
        except ValueError as e:
            print(f"排班失败：{e}")
    elif args.cmd == "twin-summary":
        print(build_summary(store, args.patient_id))
    elif args.cmd == "twin" and args.twin_cmd == "refresh":
        from .clinical.twin_v2 import build_summary_incremental
        from .clinical.twin import build_summary
        pid_str = args.twin_arg
        pid_int = int(pid_str)
        summary = build_summary(store, pid_str) if getattr(args, 'full', False) else build_summary_incremental(store, pid_int)
        print(summary)
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
        except Exception:  # nosec B110
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
    elif args.cmd == "feishu-sync":
        from .adapters import create_adapter
        adapter = create_adapter("feishu", space_id=args.space_id)
        raw_docs = adapter.pull()
        ingested = 0
        for raw in raw_docs:
            canonical = adapter.normalize(raw)
            store.store_document(canonical)
            ingested += 1
        print(f"飞书同步完成：入库 {ingested} 篇")
    elif args.cmd == "import-legacy":
        from .importer import LegacyImporter
        imp = LegacyImporter(store)
        fpath = args.file
        dry = args.dry_run
        if fpath.endswith((".xlsx", ".xls")):
            try:
                sheet = int(args.sheet)
            except ValueError:
                sheet = args.sheet
            result = imp.import_excel(fpath, sheet=sheet, dry_run=dry)
        else:
            result = imp.import_html(fpath, dry_run=dry)
        print(f"导入结果{'（预览）' if dry else ''}："
              f"患者 {result['patients']}，"
              f"病历 {result['records']}，"
              f"问诊 {result['consultations']}"
              f"{'，错误 ' + str(len(result['errors'])) if result['errors'] else ''}")
        if result["errors"]:
            for err in result["errors"][:5]:
                print(f"  ⚠ {err['error']}")
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
        desktop_dir = os.path.join(os.path.dirname(__file__), "..", "desktop")
        if args.electron:
            # Electron 模式：Electron main.js 自己启动后端，cli 不再启动
            url = f"http://127.0.0.1:{port}/"
            print(f"启动 Electron 窗口 -> {url}")
            subprocess.Popen(["npx", "electron", "main.js"],
                             cwd=desktop_dir,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             env={**os.environ, "KHUB_PORT": str(port)})
            print("按 Ctrl+C 停止服务")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n服务停止")
        else:
            # 浏览器模式：cli 启动后端，打开浏览器
            t = threading.Thread(target=serve, args=(store, lib, "127.0.0.1", port), daemon=True)
            t.start()
            time.sleep(1.5)
            url = f"http://127.0.0.1:{port}/"
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
        from .retrieval import rebuild_vec
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
            for err in report["errors"]:
                print(f"  - {err}")
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
                except Exception:  # nosec B110
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
            if args.target:
                out_db = args.target
            else:
                out_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
            if args.target and os.path.exists(out_db):
                # 安全覆盖：目标已存在则先改名备份，绝不静默覆盖（设计 §5/§8）。
                # 指向线上库时避免误毁当前数据；如需覆盖删备份或换路径即可。
                bak = f"{out_db}.bak-{int(time.time())}"
                os.rename(out_db, bak)
                # 旧库若使用 WAL 模式，关联的 -wal/-shm 文件也要一起改名，
                # 否则备份库打开时会找不到对应的 WAL 导致 I/O 错误
                for _ext in ("-wal", "-shm"):
                    _p_src = out_db + _ext
                    if os.path.exists(_p_src):
                        os.rename(_p_src, bak + _ext)
                print(f"警告：目标库 {out_db} 已存在，已备份为 {bak}；"
                      "如需覆盖请先删除备份或换路径。")
            _shutil.copy(snap_db, out_db)
            # 清理快照可能残留的 WAL / SHM 文件（前身 Store 若启用 WAL 模式
            # 会留下 -wal/-shm 文件，与新内容不兼容，须删除以防 SQLite
            # 尝试从过期 WAL 恢复导致数据异常）
            for _ext in ("-wal", "-shm"):
                _p = out_db + _ext
                if os.path.exists(_p):
                    os.remove(_p)
            restored = Store(out_db)
            rebuild_fts(restored)
            rebuild_vec(restored)
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
            # 向量索引（vec0）重建状态
            try:
                vec_models = [r["model"] for r in restored.conn.execute(
                    "SELECT DISTINCT model FROM embeddings").fetchall()]
                vec_lines = []
                for m in vec_models:
                    # 表名标识符拼接前校验：model 来自 embeddings.model，
                    # 须限定为 \w+ 才能进入 vec_{model}（与 retrieval._vec_table 约定一致）
                    if not re.fullmatch(r"\w+", m or ""):
                        vec_lines.append(f"{m}=非法模型名")
                        continue
                    t = f"vec_{m}"
                    try:
                        n = restored.conn.execute(
                            f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        vec_lines.append(f"{t}={n}")
                    except Exception:
                        vec_lines.append(f"{t}=缺失")
                print(f"  vec0       : {', '.join(vec_lines) if vec_lines else '无 embeddings'}")
            except Exception as e:
                print(f"  vec0       : 查询失败（{e}）")
            print(f"  integrity  : {vrep['integrity']}")
            print(f"  结果       : {'通过' if vrep['ok'] else '失败（见下方）'}")
            for err in vrep["errors"]:
                print(f"    - {err}")
            if not args.target:
                try:
                    os.remove(out_db)
                except OSError:
                    pass
                print("（默认已用临时库校验，未改动任何已有库；"
                      "如需落盘请加 --target <out.db>）")
            return 0 if vrep["ok"] else 1
        elif args.dr_cmd == "prune":
            # I5 — WAL 归档窗口：清理已推送(applied=1)的旧 WAL，防磁盘膨胀。
            # --keep / --keep-days 覆盖环境变量 KHUB_WAL_KEEP / KHUB_WAL_KEEP_DAYS；
            # 两者皆未给时按环境变量（仍无则默认保留全量、不清理）。
            deleted = store.prune_wal(keep=args.keep, keep_days=args.keep_days)
            remaining = store.conn.execute(
                "SELECT COUNT(*) FROM replication_log").fetchone()[0]
            print(f"=== khub dr prune ===")
            print(f"已清理 WAL  : {deleted} 条（仅 applied=1 的旧记录）")
            print(f"剩余 WAL    : {remaining} 条")
            if deleted == 0:
                env = []
                if os.environ.get("KHUB_WAL_KEEP"):
                    env.append(f"KHUB_WAL_KEEP={os.environ['KHUB_WAL_KEEP']}")
                if os.environ.get("KHUB_WAL_KEEP_DAYS"):
                    env.append(f"KHUB_WAL_KEEP_DAYS={os.environ['KHUB_WAL_KEEP_DAYS']}")
                if env:
                    print("（未达窗口阈值，无需清理；窗口=" + ", ".join(env) + "）")
                else:
                    print("（未设归档窗口：默认保留全量 WAL（PITR 无界）。"
                          "设 KHUB_WAL_KEEP / KHUB_WAL_KEEP_DAYS 或传 --keep/--keep-days 启用）")
            return 0
        else:
            pdr.print_help()
    elif args.cmd == "ha":
        from .ha import FailoverController, render_status
        from .ha.controller import LEASE_SECONDS

        peer = store.ha_get("ha_peer")
        manual = args.manual or False

        def _fc():
            return FailoverController(store, peer=peer, manual=manual)

        if not hasattr(args, "ha_cmd") or args.ha_cmd is None:
            pha.print_help()
            return 1
        if args.ha_cmd == "status":
            fc = _fc()
            print(render_status(fc))
        elif args.ha_cmd == "config":
            store.ha_set("ha_peer", args.peer)
            store.conn.commit()
            print(f"已配置 HA 对端 replica 目标：{args.peer}")
        elif args.ha_cmd == "promote":
            fc = _fc()
            st = fc.promote()
            print(f"已提升为新主（epoch={st.epoch}）")
        elif args.ha_cmd == "demote":
            fc = _fc()
            st = fc.demote()
            print(f"已降级为备（role={st.role}）")
        elif args.ha_cmd == "run":
            fc = _fc()
            if not peer:
                print("警告：未配置 HA 对端（ha_peer），请先 `khub ha config --peer ...`；"
                      "每个 tick 将跳过 WAL 回放。", file=sys.stderr)
            print(f"启动 HA 守护循环（interval={args.interval}s），按 Ctrl+C 停止...")
            try:
                fc.run(interval=args.interval, blocking=True)
            except KeyboardInterrupt:
                print("\nHA 守护循环已停止。")
        elif args.ha_cmd == "reconcile":
            from .db import Store as _S
            from .ha.reconcile import reconcile as _reconcile, format_report
            if not os.path.isfile(args.left):
                print(f"错误：左库路径不存在：{args.left}", file=sys.stderr)
                return 1
            if not os.path.isfile(args.right):
                print(f"错误：右库路径不存在：{args.right}", file=sys.stderr)
                return 1
            left = _S(args.left)
            right = _S(args.right)
            report = _reconcile(left, right)
            print(format_report(report))
        elif args.ha_cmd == "resolve":
            from .ha.reconcile import (
                resolve_split_brain as _resolve, resolve_summary)
            try:
                result = _resolve(store, args.keep)
                print(resolve_summary(result))
            except ValueError as e:
                print(f"错误：{e}", file=sys.stderr)
                return 1
        elif args.ha_cmd == "self-test":
            from .ha.selftest import (
                run_scenario as _run, run_all as _run_all,
                format_selftest)
            if args.scenario == "all":
                results = _run_all()
            else:
                results = [_run(args.scenario)]
            print(format_selftest(results))
        elif args.ha_cmd == "drill":
            import tempfile as _tf
            from .ha.drill import run_drill, format_drill
            _base = _tf.mkdtemp(prefix="khub_drill_")
            _rep = os.path.join(_base, "replica")
            _pa = os.path.join(_base, "primary.db")
            _st = os.path.join(_base, "standby.db")
            try:
                result = run_drill(_pa, _st, _rep,
                                   manual=args.manual, doc_count=args.docs)
                print(format_drill(result))
            finally:
                _shutil.rmtree(_base, ignore_errors=True)
        else:
            pha.print_help()
    elif args.cmd == "consult-chat":
        from .clinical.consult_chat import start_session, chat
        pid = args.patient_id
        sid = start_session(store, pid)
        if args.message:
            print(chat(store, sid, args.message))
        else:
            print("问诊助手已启动（输入空行退出）")
            while True:
                try:
                    msg = input("> ").strip()
                    if not msg:
                        break
                    print(chat(store, sid, msg))
                except (EOFError, KeyboardInterrupt):
                    break
    elif args.cmd == "followup-add":
        from .clinical.followup import add_plan
        pid = add_plan(store, args.pid, args.due, args.reason)
        print(f"随访计划 #{pid} 已创建")
    elif args.cmd == "followup-scan":
        from .clinical.followup import scan_due
        due = scan_due(store, as_of=args.as_of or None)
        print(f"到期随访：{len(due)} 项")
        for d in due:
            print(f"  #{d['id']} 患者{d['patient_id']} 到期日{d['due_date']} {d['reason'] or ''}")
    elif args.cmd == "followup-adherence":
        from .clinical.followup import record_adherence
        attended = False
        if args.attended:
            attended = True
        elif args.missed:
            attended = False
        record_adherence(store, args.plan_id, attended, args.note)
        print(f"随访 #{args.plan_id} 依从性记录完成")
    elif args.cmd == "record-extract":
        from .clinical.extract import extract_structured, apply_struct
        import json as _json
        row = store.conn.execute(
            "SELECT id, diagnosis, prescription FROM records WHERE id=?", (args.record_id,)
        ).fetchone()
        if not row:
            print(f"病历 #{args.record_id} 不存在")
            return
        text = f"{row['diagnosis'] or ''} {row['prescription'] or ''}"
        struct = extract_structured(store, text)
        apply_struct(store, "record", row["id"], struct)
        print(_json.dumps(struct, ensure_ascii=False, indent=2))
    elif args.cmd == "consult-extract":
        from .clinical.extract import extract_structured, apply_struct
        import json as _json
        row = store.conn.execute(
            "SELECT id, chief_complaint, differentiation FROM consultations WHERE id=?", (args.consult_id,)
        ).fetchone()
        if not row:
            print(f"问诊 #{args.consult_id} 不存在")
            return
        text = f"{row['chief_complaint'] or ''} {row['differentiation'] or ''}"
        struct = extract_structured(store, text)
        apply_struct(store, "consult", row["id"], struct)
        print(_json.dumps(struct, ensure_ascii=False, indent=2))
    elif args.cmd == "course-create":
        from .course.store import add_course
        cid = add_course(store, args.name, teacher=args.teacher, description=args.description,
                         start_date=args.start_date, end_date=args.end_date,
                         capacity=args.capacity, price=args.price)
        print(f"课程 #{cid} 已创建")
    elif args.cmd == "course-list":
        from .course.store import list_courses
        for c in list_courses(store, status=args.status or None):
            print(f"  #{c['id']} {c['name']} — {c['teacher'] or '无教师'} [{c['status']}]")
    elif args.cmd == "course-info":
        from .course.store import get_course
        c = get_course(store, args.course_id)
        if not c: print("课程不存在"); return
        print(f"名称：{c['name']}\n教师：{c['teacher'] or '(无)'}\n时间：{c['start_date'] or ''}—{c['end_date'] or ''}\n已报名：{c.get('enrolled_count',0)}/{c['capacity'] if c['capacity'] else '不限'}")
    elif args.cmd == "lesson-add":
        from .course.store import add_lesson
        lid = add_lesson(store, args.course_id, args.title, args.date,
                         start_time=args.start_time, end_time=args.end_time,
                         location=args.location)
        print(f"课时 #{lid} 已添加")
    elif args.cmd == "lesson-list":
        from .course.store import list_lessons
        for l in list_lessons(store, args.course_id):
            print(f"  #{l['id']} {l['lesson_date']} {l['title']} {l['location'] or ''}")
    elif args.cmd == "enroll":
        from .course.store import enroll_student
        try:
            eid = enroll_student(store, args.course_id, args.student_name, student_phone=args.phone)
            print(f"报名 #{eid} 成功")
        except ValueError as e:
            print(f"报名失败：{e}")
    elif args.cmd == "grade":
        from .course.store import record_grade
        gid = record_grade(store, args.enrollment_id, args.score,
                           lesson_id=args.lesson, comment=args.comment)
        print(f"成绩 #{gid} 已录入")
    elif args.cmd == "wechat-article-add":
        from .wechat.store import add_article
        aid = add_article(store, title=args.title, content=args.content,
                          author=args.author, digest=args.digest)
        print(f"文章 #{aid} 已创建（草稿）")
    elif args.cmd == "wechat-article-list":
        from .wechat.store import list_articles
        for a in list_articles(store, status=args.status or None):
            print(f"  #{a['id']} {a['title']} [{a['status']}] {a.get('wechat_url','')}")
    elif args.cmd == "wechat-schedule":
        from .wechat.store import add_schedule
        sid = add_schedule(store, args.article_id, args.publish_at)
        print(f"排期 #{sid} 已创建（{args.publish_at} 发布）")
    elif args.cmd == "wechat-publish":
        if args.due:
            from .wechat.store import scan_due_schedules, update_schedule_status
            from .wechat.api import upload_news, send_mass
            due = scan_due_schedules(store)
            if not due: print("没有到期排期"); return
            for s in due:
                print(f"发布 #{s['article_id']} {s.get('article_title','')} ...", end="")
                resp = upload_news([{
                    "title": s.get("article_title",""), "content": s.get("content",""),
                    "thumb_media_id": s.get("thumb_media_id","") or "",
                    "need_open_comment": 0, "only_fans_can_comment": 0,
                }])
                if resp.get("media_id"):
                    send_resp = send_mass({"media_id": resp["media_id"]}, is_to_all=s["tag_id"]==0, tag_id=s["tag_id"])
                    if send_resp.get("errcode", -1) == 0:
                        update_schedule_status(store, s["id"], "published")
                        print(" 已发布")
                    else:
                        update_schedule_status(store, s["id"], "failed", str(send_resp))
                        print(f" 失败：{send_resp}")
                else:
                    update_schedule_status(store, s["id"], "failed", str(resp))
                    print(f" 素材上传失败：{resp}")
    elif args.cmd == "wechat-sync-followers":
        from .wechat.api import get_followers, batchget_user_info
        from .wechat.store import sync_followers
        data = get_followers()
        openids = data.get("data", {}).get("openid", [])
        if not openids: print("无粉丝"); return
        total = data.get("total", 0)
        batch = []
        for i in range(0, len(openids), 100):
            batch.extend(batchget_user_info(openids[i:i+100]))
        sync_followers(store, batch)
        print(f"已同步 {total} 个粉丝")
    elif args.cmd == "user-list":
        from .auth import list_users
        for u in list_users(store):
            print(f"  #{u['id']} {u['username']} [{u['role']}] {'✓' if u['active'] else '✗'}")
    elif args.cmd == "user-create":
        from .auth import create_user
        uid = create_user(store, args.username, args.password,
                          display_name=args.display, role=args.role)
        print(f"用户 #{uid} 已创建")
    elif args.cmd == "user-role":
        from .auth import update_user_role
        try:
            update_user_role(store, args.user_id, args.role)
            print(f"用户 #{args.user_id} 角色已修改为 {args.role}")
        except ValueError as e:
            print(f"失败：{e}")
    elif args.cmd == "clinical-matrix":
        from .clinical.analysis import build_syndrome_formula_matrix_for_patient
        import json as _json
        print(_json.dumps(build_syndrome_formula_matrix_for_patient(store, args.patient_id), ensure_ascii=False, indent=2))
    elif args.cmd == "clinical-trends":
        from .clinical.visualize import get_health_trends
        import json as _json
        print(_json.dumps(get_health_trends(store, args.patient_id), ensure_ascii=False, indent=2))
    elif args.cmd == "clinical-suggest":
        from .clinical.diagnosis import suggest_formula, check_incompatibility
        from .llm import get_provider
        for s in suggest_formula(args.syndrome, provider=get_provider()):
            print(f"  {s['formula']} [{s['source']}]")
    elif args.cmd == "clinical-tracking":
        from .clinical.tracking import evaluate_efficacy
        e = evaluate_efficacy(store, args.patient_id)
        print(f"就诊次数：{e['visit_count']}")
        print(f"随访依从性：{e['followup_compliance']} ({e['adherence_rate']})")
        print(f"治疗连续性：{e['treatment_continuity']}")
    # 0.5.0 knowledge graph
    elif args.cmd == "kg-infer":
        from .knowledge.inference import infer; import json as _j
        print(_j.dumps(infer(store, args.syndrome), ensure_ascii=False, indent=2))
    elif args.cmd == "kg-herbs":
        from .knowledge.herbs import search_herbs
        for h in search_herbs(store, channel=args.channel, nature=args.nature):
            print(f"  {h['name']} [{h['nature']}/{h['flavor']}] 归经:{h['channel']}")
    elif args.cmd == "kg-formulas":
        from .knowledge.formulas import list_formulas
        for f in list_formulas(store, category=args.category):
            print(f"  {f['name']} [{f['source']}] {f.get('功效','')}")
    elif args.cmd == "kg-similarity":
        from .knowledge.formulas import formula_similarity
        print(f"相似度：{formula_similarity(store, args.f1, args.f2):.3f}")
    # 0.6.0 开放平台
    elif args.cmd == "plugin-list":
        from .plugins.registry import list_plugins
        plugins = list_plugins()
        if not plugins:
            print("未加载任何插件")
        for p in plugins:
            print(f"  {p['name']} v{p['version']} — {p['description']}")
    elif args.cmd == "webhook-add":
        from .webhook import subscribe
        try:
            sid = subscribe(store, args.event, args.url, args.secret)
            print(f"Webhook #{sid} 已创建")
        except ValueError as e:
            print(f"失败：{e}")
    elif args.cmd == "webhook-list":
        from .webhook import list_subscriptions
        subs = list_subscriptions(store)
        if not subs:
            print("无 Webhook 订阅")
        for s in subs:
            active_symbol = "✓" if s["active"] else "✗"
            print(f"  #{s['id']} {s['event']} → {s['url']} {active_symbol}")
    elif args.cmd == "notify-list":
        from .notifications import list_recent, unread_count
        for n in list_recent(store, args.user_id):
            print(f"  [{n['created_at']}] {'✓' if n['read'] else '○'} {n['title']} — {n['body'] or ''}")
        print(f"未读：{unread_count(store, args.user_id)}")
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
