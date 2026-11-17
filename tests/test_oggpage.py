# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oggpage  # noqa: E402


def read_hex(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def make_packets():
    """确定的包序列：含空包、255 整数倍包、跨页大包、末尾零星小包。"""
    sizes = [0, 1, 254, 255, 256, 510, 100, 3000, 5000, 7000, 40, 41, 255, 13, 7]
    return [bytes((i * 31 + j) % 256 for j in range(s))
            for i, s in enumerate(sizes)]


def make_stream():
    return oggpage.build_pages(oggpage.paginate(make_packets(), serial=42))


def page_offsets(pages):
    offs = []
    pos = 0
    for p in pages:
        offs.append(pos)
        pos += p.total_size
    return offs


# ------------------------------------------------------------ CRC

def test_crc32_ogg_matches_reference():
    def ref(data):
        crc = 0
        for byte in data:
            crc ^= byte << 24
            for _ in range(8):
                if crc & 0x80000000:
                    crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                else:
                    crc = (crc << 1) & 0xFFFFFFFF
        return crc

    assert oggpage.crc32_ogg(b"") == 0
    for sample in (b"\x00", b"OggS", bytes(range(256)), os.urandom(513)):
        assert oggpage.crc32_ogg(sample) == ref(sample)


# ------------------------------------------------------------ 分片：页边界与标志位

def test_pagination_boundaries_and_flags():
    pages = oggpage.paginate(make_packets(), serial=42)
    assert len(pages) > 1
    for p in pages:
        assert p.total_size <= 4096, "单页超过 4KB"
        assert len(p.segments) <= 255
    # 首页 BOS、末页 EOS、其余页不带 EOS
    assert pages[0].is_bos
    assert pages[-1].is_eos
    assert all(not p.is_eos for p in pages[:-1])
    # continuation 位不靠猜：当且仅当前一页末尾停在包中间（末段为 255）
    assert not pages[0].is_continuation
    for prev, cur in zip(pages, pages[1:]):
        assert cur.is_continuation == (prev.segments[-1] == 255)
    # 大红包确实被迫跨页，出现了续接页
    assert any(p.is_continuation for p in pages)
    # 页序号连续
    assert [p.sequence for p in pages] == list(range(len(pages)))
    assert all(p.serial == 42 for p in pages)


def test_small_stream_not_split():
    packets = [b"abc", b"", b"defgh"]
    pages = oggpage.paginate(packets, serial=1)
    assert len(pages) == 1, "装得下的流不应人为拆页"
    assert pages[0].is_bos and pages[0].is_eos


# ------------------------------------------------------------ 校验与容错

def test_bad_page_is_skipped():
    pages = oggpage.paginate(make_packets(), serial=42)
    data = bytearray(oggpage.build_pages(pages))
    victim = 2  # 弄坏第 2 页负载的一个字节
    off = page_offsets(pages)[victim] + 27 + len(pages[victim].segments)
    data[off] ^= 0xFF

    good, bad = oggpage.parse_pages(bytes(data))
    assert len(bad) == 1
    assert bad[0].index == victim
    assert "CRC" in bad[0].reason
    # 坏页被跳过，其余页照常解析，页数 = 总数 - 1
    assert len(good) == len(pages) - 1
    assert [p.sequence for p in good] == [i for i in range(len(pages)) if i != victim]
    # 重组不因坏页崩溃
    oggpage.depaginate(good)


def test_bad_version_and_truncated_page():
    pages = oggpage.paginate([b"x" * 100, b"y" * 100], serial=1)
    assert len(pages) == 1
    good = oggpage.build_pages(pages)

    bad_version = bytearray(good)
    bad_version[4] = 9  # 版本号越界
    stream = bytes(bad_version) + good
    parsed, bad = oggpage.parse_pages(stream)
    assert len(bad) == 1 and "版本号" in bad[0].reason
    assert len(parsed) == 1  # 后面的好页仍然解析出来

    truncated = good + b"OggS\x00\x00"  # 头部不足 27 字节
    parsed, bad = oggpage.parse_pages(truncated)
    assert len(parsed) == 1
    assert len(bad) == 1 and "截断" in bad[0].reason


# ------------------------------------------------------------ 重组

def test_reassemble_byte_identical():
    packets = make_packets()
    data = oggpage.build_pages(oggpage.paginate(packets, serial=42))
    pages, bad = oggpage.parse_pages(data)
    assert bad == []
    out = oggpage.depaginate(pages)
    assert out == packets, "重组包序列应与原始逐字节一致（含末尾零星包）"
    assert b"".join(out) == b"".join(packets)


def test_deterministic_across_runs():
    data = make_stream()
    first = oggpage.parse_pages(data)
    second = oggpage.parse_pages(data)
    assert first == second
    assert oggpage.build_pages(first[0]) == oggpage.build_pages(second[0])


def test_build_parse_roundtrip():
    data = make_stream()
    pages, bad = oggpage.parse_pages(data)
    assert bad == []
    assert oggpage.build_pages(pages) == data


# ------------------------------------------------------------ 状态：从第 N 页续解析

def test_resume_from_page_n():
    data = make_stream()
    pages_all, bad_all = oggpage.parse_pages(data)
    assert bad_all == []
    for n in (0, 1, 3, len(pages_all) - 1, len(pages_all)):
        pages_n, bad_n = oggpage.parse_pages(data, start=n)
        assert bad_n == []
        assert pages_n == pages_all[n:], "第 %d 页续解析应与整条解析的切片一致" % n


# ------------------------------------------------------------ 数据文件冒烟

def test_data_file_parses_without_crash():
    data = bytes.fromhex(read_hex("data/stream.hex"))
    pages, bad = oggpage.parse_pages(data)
    assert isinstance(pages, list)
    assert isinstance(bad, list)
