"""内容归一化：格式检测与编码修复，不修改原始内容。"""
import re


def detect_format(content: str, filename: str = "") -> str:
    """检测内容格式。返回 'html' / 'markdown' / 'plain'。"""
    stripped = content.strip()

    # 从文件名推断
    if filename:
        ext = filename.lower().rsplit(".", 1)[-1]
        if ext in ("md", "markdown"):
            return "markdown"
        if ext in ("html", "htm", "xhtml"):
            return "html"
        if ext in ("txt",):
            return "plain"

    # 从内容推断：HTML
    if stripped[:15].lower().startswith("<!doctype html") or \
       stripped[:6].lower().startswith("<html") or \
       stripped[:4].lower().startswith("<?xml"):
        return "html"
    # 包含 HTML 标签（粗略启发式）
    if "<" in stripped[:100] and ">" in stripped[:100]:
        # 检查是否有常见的 HTML 模式
        html_markers = ("<div", "<p>", "<span", "<a ", "<br", "<table", "<img", "<h1", "<h2", "<h3")
        if any(m in stripped[:500].lower() for m in html_markers):
            return "html"

    # Markdown 标记
    md_markers = ("# ", "## ", "### ", "* ", "- ", "> ", "```", "---\n", "___\n")
    if any(m in stripped[:200] for m in md_markers):
        return "markdown"

    return "plain"


def auto_decode(data: bytes) -> str:
    """自动检测编码并解码。优先 UTF-8，失败则试 GBK。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("gbk")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")
