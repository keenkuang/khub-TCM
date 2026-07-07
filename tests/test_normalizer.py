from khub.normalizer import detect_format, auto_decode


def test_detect_format_html():
    assert detect_format('<!DOCTYPE html><html><body>xxx</body></html>') == 'html'
    assert detect_format('<p>一段文字</p>') == 'html'
    assert detect_format('<div class="content">标题</div>') == 'html'


def test_detect_format_markdown():
    assert detect_format('# 标题\n正文') == 'markdown'
    assert detect_format('## 二级\n* 列表项') == 'markdown'
    assert detect_format('```python\nprint("hello")\n```') == 'markdown'


def test_detect_format_plain():
    assert detect_format('这是一段普通文字') == 'plain'
    assert detect_format('太阳病，发热汗出，桂枝汤主之。') == 'plain'


def test_detect_format_from_filename():
    assert detect_format('', filename='readme.md') == 'markdown'
    assert detect_format('', filename='article.html') == 'html'
    assert detect_format('', filename='notes.txt') == 'plain'


def test_auto_decode_utf8():
    assert auto_decode('你好'.encode('utf-8')) == '你好'


def test_auto_decode_gbk():
    gbk_bytes = '中医'.encode('gbk')
    assert auto_decode(gbk_bytes) == '中医'
