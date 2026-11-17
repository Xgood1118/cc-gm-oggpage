# -*- coding: utf-8 -*-
"""命令行入口：解析十六进制形式的 Ogg 流，校验并重组。"""

import argparse
import sys

import oggpage as m


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ogg 页分片与重组")
    ap.add_argument("input", help="输入文件：十六进制文本形式的 Ogg 流")
    ap.add_argument("--out", required=True, help="输出文件：重组后的十六进制文本")
    a = ap.parse_args(argv)

    with open(a.input, encoding="utf-8") as f:
        data = bytes.fromhex("".join(f.read().split()))

    pages, bad = m.parse_pages(data)
    rebuilt = m.build_pages(pages)

    with open(a.out, "w", encoding="ascii") as f:
        f.write(rebuilt.hex() + "\n")

    diff = sum(1 for x, y in zip(data, rebuilt) if x != y)
    diff += abs(len(data) - len(rebuilt))

    print("输入字节: %d" % len(data))
    print("页数: %d" % len(pages))
    if bad:
        print("坏页: %d" % len(bad))
        for b in bad:
            print("  第 %d 页 (偏移 %d): %s" % (b.index, b.offset, b.reason))
    else:
        print("坏页: 无")
    print("重组字节: %d" % len(rebuilt))
    print("与原始差异字节数: %d" % diff)
    return 0


if __name__ == "__main__":
    sys.exit(main())
