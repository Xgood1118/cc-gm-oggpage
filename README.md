# Ogg 页分片与重组

一个能正确分片、校验并重组 Ogg 页的封装器（仅标准库，遵循 RFC 3533 页结构）。

## 保留签名

- `OggPage`（另增 `segments` 字段保存真实段表，保证字节级往返）
- `parse_pages(data, start=0)` → `(pages, bad)`，`bad` 为 `BadPage(index, offset, reason)` 列表
- `build_pages(pages)` → `bytes`
- `crc32_ogg(data)` → `int`

另提供 `paginate(packets, serial=1, max_page_size=4096)`（分片）与
`depaginate(pages)`（重组为包序列）。

## 行为要点

- **分片**：单页总字节数 ≤ 4KB，装得下就不拆；优先按包边界断页，只有单包
  超过一页时才按 255 字节段跨页，后续页标 continuation（0x01）；首页标
  BOS（0x02），末页标 EOS（0x04），标志位由实际分页位置决定。
- **校验**：每页验证 Ogg CRC32（多项式 0x04C11DB7，初值 0，不反射不取反）。
  CRC 错、版本号越界、段表/负载截断（页长与声明不符）都记为坏页，给出页码
  与原因，跳过后继续解析，不丢弃整条流。
- **重组**：`depaginate` 按段表与 continuation 位拼包，含末尾零星包；
  因坏页缺失而接不上的残包被丢弃，不影响后续包。
- **续解析**：`parse_pages(data, start=N)` 与整条解析后取切片 `[N:]` 完全一致。

## 自测

```
python -m pytest tests -q
python -m oggpage.cli data/stream.hex --out rebuilt.hex
```

测试覆盖：页边界与 continuation 位、坏页跳过后的页数、重组字节一致性、
续解析切片一致。当前 10 项全部通过。

## 实测结果（`python -m oggpage.cli data/stream.hex --out rebuilt.hex`）

仓库自带的 `data/stream.hex` 只有 1 字节（`00`），不含任何 `OggS` 页：

- 页数：0
- 坏页页码：无
- 重组后与原始的差异字节数：1（原始 1 字节，重组后 0 字节）

在程序生成的 15 包测试流（含空包、255 整数倍包、5000/7000 字节跨页大包、
末尾零星小包）上：解析 6 页、0 坏页，重组与原始差异 0 字节；人为弄坏第 2 页
后解析出 5 页好页 + 第 2 页记入坏页（CRC 校验失败），其余页不受影响。
