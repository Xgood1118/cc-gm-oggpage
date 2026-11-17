# -*- coding: utf-8 -*-
"""Ogg 页分片与重组"""

from dataclasses import dataclass, field


@dataclass
class OggPage:
    """一页：头部字段加包负载。"""
    serial: int
    sequence: int
    flags: int
    granule: int
    payload: bytes = b""
    crc_ok: bool = True


def parse_pages(data):
    """把字节流解析成页序列，坏页记入失败列表"""
    raise NotImplementedError("parse_pages 尚未实现")


def build_pages(pages):
    """把页序列写成字节流"""
    raise NotImplementedError("build_pages 尚未实现")


def crc32_ogg(data):
    """Ogg 用的 CRC32 变体"""
    raise NotImplementedError("crc32_ogg 尚未实现")

