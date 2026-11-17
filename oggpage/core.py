# -*- coding: utf-8 -*-
"""Ogg 页分片与重组。

只依赖标准库。页结构遵循 Ogg 封装格式（RFC 3533）：

    0  4  捕获模式 "OggS"
    4  1  版本号（必须为 0）
    5  1  标志位（0x01 续接 / 0x02 BOS / 0x04 EOS）
    6  8  granule position（小端）
    14 4  流序列号 serial（小端）
    18 4  页序号 sequence（小端）
    22 4  CRC32（Ogg 变体，计算时本字段清零）
    26 1  段表项数 nseg
    27 nseg 段表（每项 0..255）
    .. .. 负载（长度为段表各项之和）
"""

from dataclasses import dataclass

__all__ = [
    "OggPage",
    "BadPage",
    "parse_pages",
    "build_pages",
    "crc32_ogg",
    "paginate",
    "depaginate",
    "MAX_PAGE_SIZE",
    "FLAG_CONTINUATION",
    "FLAG_BOS",
    "FLAG_EOS",
]

FLAG_CONTINUATION = 0x01
FLAG_BOS = 0x02
FLAG_EOS = 0x04

#: 单页总字节数（含 27 字节头与段表）上限
MAX_PAGE_SIZE = 4096

_CAPTURE = b"OggS"
_HEADER_LEN = 27
_MAX_SEGMENTS = 255


# ---------------------------------------------------------------- CRC

def _make_crc_table():
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            if r & 0x80000000:
                r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                r = (r << 1) & 0xFFFFFFFF
        table.append(r)
    return table


_CRC_TABLE = _make_crc_table()


def crc32_ogg(data):
    """Ogg 用的 CRC32 变体：多项式 0x04C11DB7，初值 0，不反射，不取反。"""
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


# ---------------------------------------------------------------- 数据类型

@dataclass
class OggPage:
    """一页：头部字段加包负载。"""
    serial: int
    sequence: int
    flags: int
    granule: int
    payload: bytes = b""
    crc_ok: bool = True
    # 段表（lacing values）。解析时填真实段表；构造时留 None 则按
    # “负载即一个完整包”自动生成。build_pages 优先使用它，保证字节级往返。
    segments: list = None

    @property
    def is_continuation(self):
        return bool(self.flags & FLAG_CONTINUATION)

    @property
    def is_bos(self):
        return bool(self.flags & FLAG_BOS)

    @property
    def is_eos(self):
        return bool(self.flags & FLAG_EOS)

    @property
    def total_size(self):
        segs = self.segments if self.segments is not None else _lacings_for(len(self.payload))
        return _HEADER_LEN + len(segs) + len(self.payload)


@dataclass
class BadPage:
    """一页解析失败的记录：第几页、偏移、原因。"""
    index: int
    offset: int
    reason: str


# ---------------------------------------------------------------- 内部工具

def _lacings_for(n):
    """长度为 n 的单个完整包对应的段表（含必要的 0 终止项）。"""
    lac = [255] * (n // 255)
    lac.append(n % 255)
    return lac


# ---------------------------------------------------------------- 解析

def parse_pages(data, start=0):
    """把字节流解析成页序列，坏页记入失败列表。

    返回 (pages, bad)：pages 是 OggPage 列表，bad 是 BadPage 列表。
    坏页（CRC 错、头部字段越界、页长与声明不符）被跳过，解析继续。
    start=N 表示只保留第 N 页（含）之后的结果，与整条解析后切片一致。
    """
    pages = []
    bad = []
    n = len(data)
    pos = 0
    index = 0
    while True:
        i = data.find(_CAPTURE, pos)
        if i < 0:
            break
        if i + _HEADER_LEN > n:
            bad.append(BadPage(index, i, "头部截断：不足 27 字节"))
            break
        version = data[i + 4]
        if version != 0:
            bad.append(BadPage(index, i, "头部字段越界：版本号 %d（应为 0）" % version))
            index += 1
            pos = i + 1
            continue
        nseg = data[i + 26]
        if i + _HEADER_LEN + nseg > n:
            bad.append(BadPage(index, i, "段表截断：声明 %d 项，剩余字节不足" % nseg))
            index += 1
            pos = i + 1
            continue
        segs = list(data[i + _HEADER_LEN: i + _HEADER_LEN + nseg])
        body = sum(segs)
        total = _HEADER_LEN + nseg + body
        if i + total > n:
            bad.append(BadPage(
                index, i,
                "页长与声明不符：声明 %d 字节，流中只剩 %d 字节" % (total, n - i)))
            index += 1
            pos = i + 1
            continue
        raw = data[i:i + total]
        stored = int.from_bytes(raw[22:26], "little")
        calc = crc32_ogg(raw[:22] + b"\x00\x00\x00\x00" + raw[26:])
        if calc != stored:
            bad.append(BadPage(
                index, i,
                "CRC 校验失败：声明 0x%08x，实算 0x%08x" % (stored, calc)))
            index += 1
            # 结构可解析，按声明长度跳过整页，避免在坏页负载里误同步
            pos = i + total
            continue
        pages.append((index, OggPage(
            serial=int.from_bytes(raw[14:18], "little"),
            sequence=int.from_bytes(raw[18:22], "little"),
            flags=raw[5],
            granule=int.from_bytes(raw[6:14], "little"),
            payload=bytes(raw[_HEADER_LEN + nseg:]),
            crc_ok=True,
            segments=segs,
        )))
        index += 1
        pos = i + total
    return (
        [p for idx, p in pages if idx >= start],
        [b for b in bad if b.index >= start],
    )


# ---------------------------------------------------------------- 写出

def build_pages(pages):
    """把页序列写成字节流。每页重新计算并填入 CRC。"""
    out = bytearray()
    for page in pages:
        segs = (list(page.segments) if page.segments is not None
                else _lacings_for(len(page.payload)))
        if len(segs) > _MAX_SEGMENTS:
            raise ValueError("第 %d 页段表 %d 项，超过 255 上限"
                             % (page.sequence, len(segs)))
        if sum(segs) != len(page.payload):
            raise ValueError("第 %d 页段表之和 %d 与负载长度 %d 不符"
                             % (page.sequence, sum(segs), len(page.payload)))
        raw = (
            _CAPTURE
            + bytes([0, page.flags & 0xFF])
            + (page.granule & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")
            + (page.serial & 0xFFFFFFFF).to_bytes(4, "little")
            + (page.sequence & 0xFFFFFFFF).to_bytes(4, "little")
            + b"\x00\x00\x00\x00"
            + bytes([len(segs)])
            + bytes(segs)
            + bytes(page.payload)
        )
        crc = crc32_ogg(raw)
        out += raw[:22] + crc.to_bytes(4, "little") + raw[26:]
    return bytes(out)


# ---------------------------------------------------------------- 分片

def paginate(packets, serial=1, max_page_size=MAX_PAGE_SIZE):
    """把一串逻辑包切成 Ogg 页。

    - 单页总字节数不超过 max_page_size（默认 4KB），装得下就不人为拆页；
    - 优先按包边界断页，不切断包；只有单个包本身就超过一页时，
      才按 255 字节段跨页，后续页标 continuation 位；
    - 首页标 BOS，最后一页标 EOS；页序号从 0 连续编号。
    """
    if max_page_size < _HEADER_LEN + 1 + 255:
        raise ValueError("max_page_size 太小，连一个最大段都放不下")
    packets = [bytes(p) for p in packets]
    if not packets:
        return []

    pages = []
    seq = 0
    segs = []            # 当前页段表
    payload = bytearray()  # 当前页负载
    cont = False         # 当前页是否以续接包开头
    mid = False          # 当前页末尾是否停在一个包的中间
    completed = 0        # 已完整写入的包数（用作 granule）

    def flush():
        nonlocal seq, segs, payload, cont, mid
        pages.append(OggPage(
            serial=serial,
            sequence=seq,
            flags=FLAG_CONTINUATION if cont else 0,
            granule=completed,
            payload=bytes(payload),
            segments=segs,
        ))
        segs = []
        payload = bytearray()
        cont = mid
        mid = False
        seq += 1

    def room_for(v):
        return (len(segs) < _MAX_SEGMENTS
                and _HEADER_LEN + len(segs) + 1 + len(payload) + v <= max_page_size)

    for pkt in packets:
        lac = _lacings_for(len(pkt))
        whole_fits = (len(segs) + len(lac) <= _MAX_SEGMENTS
                      and _HEADER_LEN + len(segs) + len(lac)
                      + len(payload) + len(pkt) <= max_page_size)
        if not whole_fits and segs:
            # 当前页装不下整个包：按包边界断页，另起新页
            flush()
            whole_fits = (len(lac) <= _MAX_SEGMENTS
                          and _HEADER_LEN + len(lac) + len(pkt) <= max_page_size)
        if whole_fits:
            segs.extend(lac)
            payload += pkt
            mid = False
            completed += 1
        else:
            # 单包超过一页，只能按 255 字节段跨页切开
            off = 0
            for v in lac:
                if not room_for(v):
                    flush()
                segs.append(v)
                payload += pkt[off:off + v]
                off += v
                mid = (v == 255)
            completed += 1
    if segs:
        flush()

    pages[0].flags |= FLAG_BOS
    pages[-1].flags |= FLAG_EOS
    return pages


def depaginate(pages):
    """把页序列重组为原始包序列（含末尾零星包）。

    跨页的包按 continuation 位拼接；因坏页被跳过而接不上的
    残缺包会被丢弃，不影响后续包。
    """
    packets = []
    cur = bytearray()
    open_pkt = False  # cur 里有一个尚未收尾的包
    for page in pages:
        segs = (page.segments if page.segments is not None
                else _lacings_for(len(page.payload)))
        pos = 0
        if page.flags & FLAG_CONTINUATION:
            # 续接页但前页缺失（坏页被跳过）：丢掉接不上的残包头部
            skipping = not open_pkt
        else:
            if open_pkt:
                # 前一个包没有续接页，残缺，丢弃
                cur.clear()
                open_pkt = False
            skipping = False
        for v in segs:
            chunk = page.payload[pos:pos + v]
            pos += v
            if skipping:
                if v < 255:
                    skipping = False
                continue
            cur += chunk
            if v < 255:
                packets.append(bytes(cur))
                cur.clear()
                open_pkt = False
            else:
                open_pkt = True
    return packets
