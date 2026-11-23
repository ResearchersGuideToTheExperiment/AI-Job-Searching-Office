"""Lossless, overlapping UTF-8 bounded windows for the existing 8K model context."""
def split_text(text: str, limit: int = 5500, overlap: int = 350) -> list[str]:
    if not text.strip():
        raise ValueError('No readable text supplied.')
    if overlap >= limit or limit < 100:
        raise ValueError('Invalid chunk size')
    chunks, start = [], 0
    while start < len(text):
        end, size = start, 0
        while end < len(text) and size + len(text[end].encode('utf-8')) <= limit:
            size += len(text[end].encode('utf-8'))
            end += 1
        if end < len(text):
            boundary = text.rfind('\n', start + (end - start) // 2, end)
            if boundary > start:
                end = boundary + 1
        chunks.append(text[start:end])
        if end == len(text):
            break
        next_start, count = end, 0
        while next_start > start + 1 and count < overlap:
            next_start -= 1
            count += len(text[next_start].encode('utf-8'))
        # Never begin an overlapping window inside a word. Prefer a complete
        # following paragraph; the previous window already contains the overlap.
        boundary=text.find('\n',next_start,end-1)
        if boundary>=0:
            next_start=boundary+1
        else:
            while next_start<end and not text[next_start-1].isspace():
                next_start+=1
        start = next_start
    return chunks
