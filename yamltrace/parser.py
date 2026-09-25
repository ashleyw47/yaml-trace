"""A parser for the subset of YAML that config files actually use.

Block mappings, block sequences (including the common `- key: value`
shorthand), plain/quoted scalars, and single-line flow collections
(`[1, 2]`, `{a: 1}`). No anchors, no tags, no multi-document streams,
no flow collections that span multiple lines. Pulling in a full YAML
library for a tool this small felt worse than owning the indentation
bookkeeping ourselves, and config files rarely reach for the exotic
corners of the spec anyway.

A key repeated within the same mapping is a parse error rather than
silent last-value-wins: a tool whose whole job is telling you where a
value came from should not itself guess which of two definitions you
meant.

Every mapping remembers the source line of each of its keys, since that
is the whole point of this tool: knowing not just a value but where it
came from.
"""

from __future__ import annotations


class YamlError(ValueError):
    def __init__(self, message, filename, lineno):
        super().__init__(f"{filename}:{lineno}: {message}")
        self.filename = filename
        self.lineno = lineno


class YMap(dict):
    """A mapping that remembers which line defined each key."""

    def __init__(self):
        super().__init__()
        self.lines = {}

    def set(self, key, value, lineno, filename):
        if key in self:
            raise YamlError(
                f"duplicate key {key!r} (first set on line {self.lines[key]})",
                filename,
                lineno,
            )
        self[key] = value
        self.lines[key] = lineno


class YList(list):
    pass


def parse(text, filename="<string>"):
    lines = _preprocess(text, filename)
    if not lines:
        return YMap()
    cursor = _Cursor(lines)
    return _parse_block(cursor, lines[0][0], filename)


class _Cursor:
    def __init__(self, lines):
        self.lines = lines
        self.i = 0

    def peek(self):
        return self.lines[self.i] if self.i < len(self.lines) else None

    def advance(self):
        self.i += 1


def _is_dash(content):
    return content == "-" or content.startswith("- ")


def _preprocess(text, filename):
    result = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        leading = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" in leading:
            raise YamlError("tabs are not allowed in indentation", filename, lineno)
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        content = stripped[indent:].rstrip()
        if content in ("---", "..."):
            continue
        result.append((indent, content, lineno))
    return result


def _strip_comment(line):
    in_single = False
    in_double = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if i == 0 or line[i - 1] in " \t":
                return line[:i]
    return line


def _parse_block(cursor, indent, filename):
    line = cursor.peek()
    if line is None:
        return YMap()
    if line[0] != indent:
        raise YamlError("unexpected indentation", filename, line[2])
    if _is_dash(line[1]):
        return _parse_sequence(cursor, indent, filename)
    return _parse_mapping(cursor, indent, filename)


def _parse_sequence(cursor, indent, filename):
    items = YList()
    while True:
        line = cursor.peek()
        if line is None or line[0] != indent or not _is_dash(line[1]):
            break
        item_indent, content, lineno = line
        rest = content[1:]
        pad = len(rest) - len(rest.lstrip(" "))
        rest = rest.lstrip(" ")
        content_indent = item_indent + 1 + pad
        cursor.advance()

        if rest == "":
            nxt = cursor.peek()
            items.append(_parse_block(cursor, nxt[0], filename) if nxt and nxt[0] > indent else None)
            continue

        key_value = _split_key_value(rest)
        if key_value is None:
            items.append(_parse_value(rest, lineno, filename))
            continue

        key, value_str = key_value
        entry = YMap()
        _consume_mapping_entry(entry, key, value_str, lineno, cursor, content_indent, filename)
        while True:
            nxt = cursor.peek()
            if nxt is None or nxt[0] != content_indent:
                break
            key2_value = _split_key_value(nxt[1])
            if key2_value is None:
                raise YamlError(f"expected 'key: value', got {nxt[1]!r}", filename, nxt[2])
            cursor.advance()
            key2, value2_str = key2_value
            _consume_mapping_entry(entry, key2, value2_str, nxt[2], cursor, content_indent, filename)
        items.append(entry)
    return items


def _parse_mapping(cursor, indent, filename):
    result = YMap()
    while True:
        line = cursor.peek()
        if line is None or line[0] != indent:
            break
        _, content, lineno = line
        key_value = _split_key_value(content)
        if key_value is None:
            raise YamlError(f"expected 'key: value', got {content!r}", filename, lineno)
        key, value_str = key_value
        cursor.advance()
        _consume_mapping_entry(result, key, value_str, lineno, cursor, indent, filename)
    return result


def _consume_mapping_entry(target, key, value_str, lineno, cursor, indent, filename):
    if value_str == "":
        nxt = cursor.peek()
        if nxt is not None and nxt[0] > indent:
            target.set(key, _parse_block(cursor, nxt[0], filename), lineno, filename)
        else:
            target.set(key, None, lineno, filename)
    else:
        target.set(key, _parse_value(value_str, lineno, filename), lineno, filename)


def _split_key_value(content):
    """Split 'key: value' at the first unquoted, unnested top-level colon.

    A colon inside a flow collection (`{a: 1}`, `[1, 2]`) doesn't count,
    so a line whose whole content is a flow value -- e.g. a sequence
    item `- {a: 1}` -- isn't mistaken for a 'key: value' pair.
    """
    in_single = False
    in_double = False
    depth = 0
    for i, ch in enumerate(content):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif in_single or in_double:
            continue
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            if i + 1 == len(content) or content[i + 1] in " \t":
                key = _parse_scalar(content[:i])
                return str(key), content[i + 1:].strip()
    return None


def _parse_scalar(text):
    s = text.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return _unescape_double(s[1:-1])
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _unescape_double(s):
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] in escapes:
            out.append(escapes[s[i + 1]])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


# Plain scalars inside flow collections stop at structural characters.
# Values don't stop at ':' -- "08:00" is a legitimate plain scalar once
# we're past the key -- but a bare key does, since that's how we know
# where the key ends and the value begins.
_FLOW_VALUE_STOP = ",{}[]"
_FLOW_KEY_STOP = ",{}[]:"


def _parse_value(text, lineno, filename):
    """Parse the value half of 'key: value', dispatching to flow
    collections when the value opens with `[` or `{`.
    """
    s = text.strip()
    if s[:1] in ("[", "{"):
        value, end = _parse_flow_value(s, 0, lineno, filename)
        end = _skip_flow_ws(s, end)
        if end != len(s):
            raise YamlError(
                f"unexpected content after flow collection: {s[end:]!r}", filename, lineno
            )
        return value
    return _parse_scalar(s)


def _skip_flow_ws(s, i):
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _parse_flow_value(s, i, lineno, filename):
    i = _skip_flow_ws(s, i)
    if i >= len(s):
        raise YamlError("unexpected end of flow collection", filename, lineno)
    ch = s[i]
    if ch == "[":
        return _parse_flow_seq(s, i, lineno, filename)
    if ch == "{":
        return _parse_flow_map(s, i, lineno, filename)
    if ch == '"':
        return _parse_flow_double(s, i, filename, lineno)
    if ch == "'":
        return _parse_flow_single(s, i, filename, lineno)
    start = i
    while i < len(s) and s[i] not in _FLOW_VALUE_STOP:
        i += 1
    return _parse_scalar(s[start:i]), i


def _parse_flow_key(s, i, filename, lineno):
    i = _skip_flow_ws(s, i)
    if i < len(s) and s[i] == '"':
        value, i = _parse_flow_double(s, i, filename, lineno)
        return str(value), i
    if i < len(s) and s[i] == "'":
        value, i = _parse_flow_single(s, i, filename, lineno)
        return str(value), i
    start = i
    while i < len(s) and s[i] not in _FLOW_KEY_STOP:
        i += 1
    return str(_parse_scalar(s[start:i])), i


def _parse_flow_double(s, i, filename, lineno):
    i += 1
    start = i
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            i += 2
            continue
        if s[i] == '"':
            return _unescape_double(s[start:i]), i + 1
        i += 1
    raise YamlError("unterminated double-quoted string in flow collection", filename, lineno)


def _parse_flow_single(s, i, filename, lineno):
    i += 1
    out = []
    while i < len(s):
        if s[i] == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(s[i])
        i += 1
    raise YamlError("unterminated single-quoted string in flow collection", filename, lineno)


def _parse_flow_seq(s, i, lineno, filename):
    i += 1  # skip '['
    items = YList()
    i = _skip_flow_ws(s, i)
    if i < len(s) and s[i] == "]":
        return items, i + 1
    while True:
        value, i = _parse_flow_value(s, i, lineno, filename)
        items.append(value)
        i = _skip_flow_ws(s, i)
        if i >= len(s):
            raise YamlError("unterminated flow sequence", filename, lineno)
        if s[i] == ",":
            i = _skip_flow_ws(s, i + 1)
            if i < len(s) and s[i] == "]":
                return items, i + 1
            continue
        if s[i] == "]":
            return items, i + 1
        raise YamlError(
            f"expected ',' or ']' in flow sequence, got {s[i]!r}", filename, lineno
        )


def _parse_flow_map(s, i, lineno, filename):
    i += 1  # skip '{'
    result = YMap()
    i = _skip_flow_ws(s, i)
    if i < len(s) and s[i] == "}":
        return result, i + 1
    while True:
        key, i = _parse_flow_key(s, i, filename, lineno)
        i = _skip_flow_ws(s, i)
        if i >= len(s) or s[i] != ":":
            raise YamlError(
                f"expected ':' after flow mapping key {key!r}", filename, lineno
            )
        value, i = _parse_flow_value(s, i + 1, lineno, filename)
        result.set(key, value, lineno, filename)
        i = _skip_flow_ws(s, i)
        if i >= len(s):
            raise YamlError("unterminated flow mapping", filename, lineno)
        if s[i] == ",":
            i = _skip_flow_ws(s, i + 1)
            if i < len(s) and s[i] == "}":
                return result, i + 1
            continue
        if s[i] == "}":
            return result, i + 1
        raise YamlError(
            f"expected ',' or '}}' in flow mapping, got {s[i]!r}", filename, lineno
        )
