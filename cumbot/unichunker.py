import io

import uniseg.linebreak


def chunker(inp, max_length):
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
