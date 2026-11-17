# Ogg 页分片与重组

一个能正确分片、校验并重组 Ogg 页的封装器

## 保留签名

- `OggPage`
- `parse_pages(data)`
- `build_pages(pages)`
- `crc32_ogg(data)`

## 自测

```
python -m pytest tests -q
python -m oggpage.cli data/stream.hex --out rebuilt.hex
```
