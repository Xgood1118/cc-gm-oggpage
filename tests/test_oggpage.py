# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oggpage as mod  # noqa: E402
oggpage = mod

def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_hex(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def test_page_roundtrip():
    data = read_hex("data/stream.hex")
    pages, bad = oggpage.parse_pages(data)
    assert pages, "解析不出页"
    assert oggpage.build_pages(pages) == data


def test_bad_page_is_skipped():
    data = read_hex("data/stream.hex")
    pages, bad = oggpage.parse_pages(data)
    assert bad, "这份数据含坏页，应当被识别"
    assert len(pages) + len(bad) >= 1
