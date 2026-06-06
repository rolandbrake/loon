#!/usr/bin/env python3
"""
to_json.py - Convert LOON (Lightweight Object Outline Notation) text back to JSON.

This parser supports the LOON shapes emitted by to_loon.py:
  - indentation-based objects
  - keyed nested values: key:\n  ...
  - primitive key/value lines: key: value
  - compact tables: key(col1, col2):\n  val1, val2
  - root-level tables: (col1, col2):\n  val1, val2
  - inline primitive lists: [1, "x", true]
  - block lists using [ and ]
  - inline flat objects: {key: value, "odd key": value}
  - explicit empty objects: {}

Usage:
    python to_json.py [input.loon] [-o output.json]
    cat data.loon | python to_json.py
"""

import argparse
import json
import re
import sys

INDENT_WIDTH = 2
NUMBER_REGEX = re.compile(
    r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$"
)


class LOONParseError(ValueError):
    """Raised when LOON input cannot be parsed."""


def split_top_level(text, delimiter=","):
    """Split *text* on delimiter characters outside quotes/brackets/braces."""
    parts = []
    start = 0
    depth = 0
    in_string = False
    escape = False

    for i, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
            if depth < 0:
                raise LOONParseError(f"Unbalanced closing bracket in {text!r}")
        elif char == delimiter and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1

    if in_string:
        raise LOONParseError(f"Unterminated string in {text!r}")
    if depth != 0:
        raise LOONParseError(f"Unbalanced brackets in {text!r}")

    parts.append(text[start:].strip())
    return parts


def split_key_value(text):
    """Split a key/value expression at the first top-level colon."""
    depth = 0
    in_string = False
    escape = False

    for i, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth -= 1
            if depth < 0:
                raise LOONParseError(f"Unbalanced closing bracket in {text!r}")
        elif char == ":" and depth == 0:
            return text[:i].strip(), text[i + 1:].strip()

    if in_string:
        raise LOONParseError(f"Unterminated string in {text!r}")
    raise LOONParseError(f"Expected ':' in {text!r}")


def find_top_level_open_paren(text):
    """Return the index of a top-level '(' whose matching ')' ends *text*."""
    depth = 0
    in_string = False
    escape = False
    candidate = None

    for i, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "(":
            if depth == 0:
                candidate = i
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise LOONParseError(f"Unbalanced ')' in {text!r}")
            if depth == 0 and i != len(text) - 1:
                candidate = None
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth < 0:
                raise LOONParseError(f"Unbalanced bracket in {text!r}")

    if in_string:
        raise LOONParseError(f"Unterminated string in {text!r}")
    return candidate if depth == 0 else None


def parse_key(text):
    """Parse a bare or JSON-quoted LOON object key."""
    text = text.strip()
    if not text:
        return ""
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LOONParseError(f"Invalid quoted key {text!r}: {exc}") from exc
        if not isinstance(value, str):
            raise LOONParseError(f"Quoted key must decode to a string: {text!r}")
        return value
    return text


def parse_scalar(text):
    """Parse a primitive LOON literal."""
    text = text.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if text.startswith('"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LOONParseError(f"Invalid string literal {text!r}: {exc}") from exc
    if NUMBER_REGEX.match(text):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LOONParseError(f"Invalid number literal {text!r}: {exc}") from exc
    raise LOONParseError(f"Unknown literal {text!r}")


def parse_inline_object(text):
    """Parse an inline object such as {a: 1, "b:c": "x"}."""
    inner = text[1:-1].strip()
    if not inner:
        return {}

    obj = {}
    for pair in split_top_level(inner):
        key_text, value_text = split_key_value(pair)
        obj[parse_key(key_text)] = parse_inline_value(value_text)
    return obj


def parse_inline_array(text):
    """Parse an inline array such as [1, "x", null]."""
    inner = text[1:-1].strip()
    if not inner:
        return []
    return [parse_inline_value(part) for part in split_top_level(inner)]


def parse_inline_value(text):
    """Parse a single-line LOON value."""
    text = text.strip()
    if text == "{}":
        return {}
    if text == "[]":
        return []
    if text.startswith("{") and text.endswith("}"):
        return parse_inline_object(text)
    if text.startswith("[") and text.endswith("]"):
        return parse_inline_array(text)
    return parse_scalar(text)


def parse_table_header(text):
    """
    Parse a table header.

    Returns (name, columns), where name is None for a root-level table.
    Returns None if *text* is not a table header.
    """
    if not text.endswith(":"):
        return None

    header = text[:-1].strip()
    open_index = find_top_level_open_paren(header)
    if open_index is None:
        return None
    if not header.endswith(")"):
        return None

    name_text = header[:open_index].strip()
    columns_text = header[open_index + 1:-1].strip()
    if not columns_text:
        raise LOONParseError("Table header must contain at least one column")

    columns = [parse_key(part) for part in split_top_level(columns_text)]
    name = None if not name_text else parse_key(name_text)
    return name, columns


class LOONParser:
    def __init__(self, text):
        self.lines = self._prepare_lines(text)
        self.pos = 0

    def _prepare_lines(self, text):
        lines = []
        for line_no, raw_line in enumerate(text.splitlines(), start=1):
            if not raw_line.strip():
                continue

            leading = len(raw_line) - len(raw_line.lstrip(" "))
            if raw_line[:leading].replace(" ", ""):
                raise LOONParseError(f"Line {line_no}: indentation must use spaces")
            if leading % INDENT_WIDTH != 0:
                raise LOONParseError(
                    f"Line {line_no}: indentation must be a multiple of {INDENT_WIDTH}"
                )

            lines.append((leading // INDENT_WIDTH, raw_line.strip(), line_no))
        return lines

    def current(self):
        if self.pos >= len(self.lines):
            return None
        return self.lines[self.pos]

    def parse(self):
        if not self.lines:
            raise LOONParseError("Empty LOON input")

        result = self.parse_value_at_indent(self.lines[0][0])
        if self.pos != len(self.lines):
            _, text, line_no = self.current()
            raise LOONParseError(f"Line {line_no}: unexpected trailing content {text!r}")
        return result

    def parse_value_at_indent(self, indent):
        current = self.current()
        if current is None:
            raise LOONParseError("Unexpected end of input")

        line_indent, text, line_no = current
        if line_indent != indent:
            raise LOONParseError(
                f"Line {line_no}: expected indent {indent}, found {line_indent}"
            )

        table = parse_table_header(text)
        if table and table[0] is None:
            return self.parse_table(indent, table[1])

        if text == "[":
            return self.parse_block_list(indent)
        if text == "{":
            return self.parse_braced_object(indent)
        if self.looks_like_object_entry(text):
            return self.parse_object(indent)

        self.pos += 1
        return parse_inline_value(text)

    def looks_like_object_entry(self, text):
        if parse_table_header(text):
            return True
        try:
            split_key_value(text)
            return True
        except LOONParseError:
            return False

    def parse_object(self, indent):
        obj = {}

        while self.pos < len(self.lines):
            line_indent, text, line_no = self.current()
            if line_indent < indent:
                break
            if line_indent > indent:
                raise LOONParseError(
                    f"Line {line_no}: unexpected nested line without a parent"
                )
            if text in ("}", "]"):
                break

            table = parse_table_header(text)
            if table and table[0] is not None:
                name, columns = table
                obj[name] = self.parse_table(indent, columns)
                continue

            key_text, value_text = split_key_value(text)
            key = parse_key(key_text)
            self.pos += 1

            if value_text:
                obj[key] = parse_inline_value(value_text)
                continue

            next_line = self.current()
            if next_line is None or next_line[0] <= indent:
                obj[key] = {}
            else:
                obj[key] = self.parse_value_at_indent(indent + 1)

        return obj

    def parse_table(self, indent, columns):
        self.pos += 1
        rows = []

        while self.pos < len(self.lines):
            line_indent, text, line_no = self.current()
            if line_indent <= indent:
                break
            if line_indent != indent + 1:
                raise LOONParseError(
                    f"Line {line_no}: table rows must be indented one level"
                )

            values = [parse_inline_value(part) for part in split_top_level(text)]
            if len(values) != len(columns):
                raise LOONParseError(
                    f"Line {line_no}: expected {len(columns)} table values, "
                    f"found {len(values)}"
                )
            rows.append(dict(zip(columns, values)))
            self.pos += 1

        return rows

    def parse_block_list(self, indent):
        self.pos += 1
        items = []

        while self.pos < len(self.lines):
            line_indent, text, line_no = self.current()
            if line_indent == indent and text == "]":
                self.pos += 1
                return items
            if line_indent != indent + 1:
                raise LOONParseError(
                    f"Line {line_no}: list items must be indented one level"
                )

            if text == "{":
                items.append(self.parse_braced_object(indent + 1))
            elif text == "[":
                items.append(self.parse_block_list(indent + 1))
            elif text == "{}":
                self.pos += 1
                items.append({})
            elif text.startswith("{") and text.endswith("}"):
                self.pos += 1
                items.append(parse_inline_object(text))
            elif text.startswith("[") and text.endswith("]"):
                self.pos += 1
                items.append(parse_inline_array(text))
            else:
                self.pos += 1
                items.append(parse_inline_value(text))

        raise LOONParseError("Unclosed list block")

    def parse_braced_object(self, indent):
        self.pos += 1
        obj = self.parse_object(indent + 1)

        current = self.current()
        if current is None:
            raise LOONParseError("Unclosed object block")
        line_indent, text, line_no = current
        if line_indent != indent or text != "}":
            raise LOONParseError(f"Line {line_no}: expected closing '}}'")

        self.pos += 1
        return obj


def loon_to_json_data(text):
    """Parse LOON text and return the equivalent Python JSON data."""
    return LOONParser(text).parse()


def read_input(path):
    """Read raw LOON text from *path*, or from stdin if *path* is None."""
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


def write_output(path, content):
    """Write *content* to *path*, or print it to stdout if *path* is None."""
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        print(content)


def main():
    parser = argparse.ArgumentParser(
        description="Convert LOON format back to JSON."
    )
    parser.add_argument("input", nargs="?", help="Input LOON file (default: stdin)")
    parser.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of pretty-printed JSON",
    )
    args = parser.parse_args()

    try:
        raw_input = read_input(args.input)
        data = loon_to_json_data(raw_input)
        if args.compact:
            result = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        else:
            result = json.dumps(data, ensure_ascii=False, indent=2)
        write_output(args.output, result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
