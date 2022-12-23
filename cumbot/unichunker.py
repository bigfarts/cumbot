import io
import itertools

import uniseg.linebreak


def chunks(inp, max_length):
    buf = io.StringIO()

    for unit in uniseg.linebreak.line_break_units(inp):
        if buf.tell() + len(unit) > max_length:
            s = buf.getvalue()
            if s:
                yield s
            buf = io.StringIO()

        buf.write(unit)

        while buf.tell() > max_length:
            s = buf.getvalue()
            yield s[:max_length]
            tail = s[max_length:]

            buf = io.StringIO()
            buf.write(tail)

    s = buf.getvalue()
    if s:
        yield s


class IncrementalChunker:
    def __init__(self, max_length):
        self.buf = io.StringIO()
        self.max_length = max_length

    def write(self, s):
        self.buf.write(s)
        if self.buf.tell() > self.max_length:
            it, peeker = itertools.tee(chunks(self.buf.getvalue(), self.max_length), 2)
            next(peeker, None)

            for chunk, _ in zip(it, peeker):
                yield chunk

            self.buf = io.StringIO()
            self.buf.write(next(it, ""))

    def flush(self):
        s = self.buf.getvalue()
        self.buf = io.StringIO()
        return s
