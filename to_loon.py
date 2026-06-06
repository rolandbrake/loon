#!/usr/bin/env python3
"""
to_loon.py - Convert JSON to compact LOON (Lightweight Object Outline Notation).

LOON reduces token and byte counts by:
  - Dropping redundant braces, brackets, and quotes where possible
  - Collapsing uniform lists-of-dicts into a table with a single header row
  - Rendering flat primitive lists inline (e.g. [1, 2, 3])
  - Indenting nested structures rather than using JSON separators

Usage:
    python to_loon.py [input.json] [-o output.loon]
    cat data.json | python to_loon.py
"""

import json
import argparse
import sys
import re
import math

# Number of spaces per indent level
INDENT = "  "


# ------------------------
# ANSI COLOR CODES
# Used for the size report printed to stdout after conversion.
# ------------------------
RESET  = "0"
BOLD   = "1"
RED    = "31"
GREEN  = "32"
YELLOW = "33"
BLUE   = "34"
CYAN   = "36"


def color(text, code):
    """Wrap *text* in an ANSI escape sequence for the given color *code*."""
    return f"\033[{code}m{text}\033[0m"


# ------------------------
# TOKEN ESTIMATION
# A rough tokenizer that mimics how LLM tokenizers split LOON output.
# Counts identifiers, numbers, quoted strings, and structural symbols
# so we can report the before/after token delta.
# ------------------------

TOKEN_REGEX = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*"  # identifiers / keywords
    r"|[-]?\d+(\.\d+)?"         # integers and floats
    r'"(?:\\.|[^"\\])*"'        # JSON-style quoted strings
    r"|[{}\[\]:,]"              # structural symbols
)

IDENTIFIER_REGEX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def count_tokens(text):
    """Return an estimated token count for *text* using TOKEN_REGEX."""
    return len(TOKEN_REGEX.findall(text))


# ------------------------
# VALUE FORMATTING
# Converts Python values to their LOON string representation.
# Strings use single quotes; booleans and null use lowercase keywords.
# ------------------------

def format_value(value):
    """Serialize a primitive Python value to its LOON literal."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    elif value is True:
        return "true"
    elif value is False:
        return "false"
    elif value is None:
        return "null"
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("LOON cannot represent non-finite JSON numbers")
        return json.dumps(value)
    else:
        return str(value)   # int / float


def format_key(key):
    """
    Serialize an object key or table column name.

    Plain identifier-like keys stay bare for compactness. Everything else is
    quoted with JSON string escaping so any valid JSON object key can be
    represented without colliding with LOON punctuation or indentation.
    """
    if not isinstance(key, str):
        raise TypeError(f"JSON object keys must be strings, got {type(key).__name__}")
    if IDENTIFIER_REGEX.match(key):
        return key
    return json.dumps(key, ensure_ascii=False)


# ------------------------
# TABLE DETECTION
# A list qualifies for the compact table format only when every row is a
# plain dict with identical keys AND every cell value is a primitive.
# This prevents nested structures from being mangled into a flat row.
# ------------------------

def is_primitive(value):
    """Return True for scalar values (str, int, float, bool, None)."""
    return not isinstance(value, (dict, list))


def is_table_candidate(lst):
    """
    Decide whether *lst* should be rendered as a compact column table.

    Rules (ALL must hold):
      1. More than one item  — single-item lists expand normally so that
         any nested values inside them are rendered correctly.
      2. Every item is a dict with the exact same keys in the same order.
      3. Every cell value is a primitive  — nested dicts/lists cannot be
         inlined into a CSV-style table row without losing structure.
    """
    # Rule 1: need at least two rows for a table to be worth it
    if not isinstance(lst, list) or len(lst) < 2:
        return False

    # Rule 2a: all items must be dicts
    if not all(isinstance(item, dict) for item in lst):
        return False

    # Zero-column tables are ambiguous; render [{}, {}] as normal list items.
    if not lst[0]:
        return False

    # Rule 2b: all dicts must share the exact same key set and order
    keys = list(lst[0].keys())
    if not all(list(item.keys()) == keys for item in lst):
        return False

    # Rule 3: every cell must be a primitive (no nested structure)
    return all(
        is_primitive(item[k])
        for item in lst
        for k in keys
    )


# ------------------------
# SHARED TABLE RENDERER
# Both convert_object (keyed tables) and convert_any (root-level tables)
# delegate here so the output format is always identical.
#
# Output with a parent key:
#     parentKey(col1, col2, col3):
#       val1, val2, val3
#       val1, val2, val3
#
# Output at root level (header_prefix is ""):
#     (col1, col2, col3):
#       val1, val2, val3
# ------------------------

def render_table(lst, columns, indent, header_prefix=""):
    """
    Render a table-candidate list as a compact column table.

    Parameters
    ----------
    lst           : list of dicts — the rows to render
    columns       : list of str  — column names (from lst[0].keys())
    indent        : int          — current indentation level
    header_prefix : str          — parent key name, or "" for root-level lists
    """
    prefix     = INDENT * indent          # indent for the header line
    row_prefix = INDENT * (indent + 1)    # indent for each data row

    lines = []
    # Header line: key(col1, col2, ...) or just (col1, col2, ...) at root
    formatted_columns = [format_key(column) for column in columns]
    lines.append(f"{prefix}{header_prefix}({', '.join(formatted_columns)}):")

    # One data row per dict, values comma-separated in column order
    for row in lst:
        row_values = [format_value(row[col]) for col in columns]
        lines.append(f"{row_prefix}{', '.join(row_values)}")

    return lines


# ------------------------
# INLINE DICT RENDERER
# Used when a dict appears as an element inside a list (not as a named field
# of a parent object).  Two shapes are possible:
#
#   Flat  (all values primitive):  {key: val, key: val}   ← single line
#   Deep  (has nested values):     {                       ← block form
#                                    key: val
#                                    nested:
#                                      ...
#                                  }
#
# The flat form keeps rows compact; the block form preserves readability
# when a list item itself contains nested objects or lists.
# ------------------------

def inline_dict(obj, indent):
    """
    Render a dict that lives inside a list (not a named object field).

    If all values are primitives the dict is written on one line:
        {k1: v1, k2: v2}

    Otherwise a bracketed block is used so nested content isn't squashed:
        {
          k1: v1
          k2:
            nested_val
        }
    """
    # Flat case: every value is a primitive -> single-line {k: v, ...}
    if not obj:
        return [(INDENT * indent) + "{}"]

    if all(is_primitive(v) for v in obj.values()):
        pairs = ", ".join(f"{format_key(k)}: {format_value(v)}" for k, v in obj.items())
        return [(INDENT * indent) + "{" + pairs + "}"]

    # Deep case: at least one value is a dict or list -> block form
    prefix = INDENT * indent
    lines  = [f"{prefix}{{"]
    lines.extend(convert_object(obj, indent + 1))
    lines.append(f"{prefix}}}")
    return lines


# ------------------------
# OBJECT CONVERSION
# Converts a JSON object (dict) to LOON lines.
# Each key is rendered differently depending on its value type:
#   - Nested dict  -> key:\n  <recursive>
#   - Table list   -> key(col1, col2):\n  val, val  (via render_table)
#   - Other list   -> key:\n  <recursive convert_any>
#   - Primitive    -> key: value
# ------------------------

def convert_object(obj, indent=0):
    """
    Convert a dict *obj* to a list of LOON text lines at indentation *indent*.
    """
    lines  = []
    prefix = INDENT * indent

    if not obj:
        return [f"{prefix}{{}}"]

    for key, value in obj.items():
        formatted_key = format_key(key)

        if isinstance(value, dict):
            if value:
                # Nested object: print the key as a section header, recurse
                lines.append(f"{prefix}{formatted_key}:")
                lines.extend(convert_object(value, indent + 1))
            else:
                lines.append(f"{prefix}{formatted_key}: {{}}")

        elif isinstance(value, list):
            if is_table_candidate(value):
                # Uniform primitive rows -> compact column table
                columns = list(value[0].keys())
                lines.extend(render_table(value, columns, indent, header_prefix=formatted_key))
            else:
                # Heterogeneous or nested list -> expand with convert_any
                lines.append(f"{prefix}{formatted_key}:")
                nested = convert_any(value, indent + 1)
                lines.extend(nested.split("\n"))

        else:
            # Primitive value -> single key: value line
            lines.append(f"{prefix}{formatted_key}: {format_value(value)}")

    return lines


# ------------------------
# GENERIC VALUE CONVERSION
# Entry point for any JSON value (dict, list, or primitive).
# Called recursively for nested structures and directly for the root value.
# ------------------------

def convert_any(value, indent=0):
    """
    Convert any JSON value to its LOON string representation.

    Dispatches to convert_object for dicts, and handles three list cases:
      1. Table candidate  -> render_table (column header + primitive rows)
      2. Flat primitive   -> inline  [val, val, val]
      3. Mixed / nested   -> bracketed block with one entry per line
    """
    prefix = INDENT * indent

    if isinstance(value, dict):
        return "\n".join(convert_object(value, indent))

    elif isinstance(value, list):

        # Case 1: uniform primitive rows -> column-header table
        if is_table_candidate(value):
            columns = list(value[0].keys())
            # header_prefix="" because there is no parent key at this call site
            return "\n".join(render_table(value, columns, indent, header_prefix=""))

        # Case 2: all primitive values -> compact inline list
        if all(is_primitive(v) for v in value):
            return f"{prefix}[{', '.join(format_value(v) for v in value)}]"

        # Case 3: mixed or nested list -> bracketed block, one item per line.
        # Dicts are wrapped in {} via inline_dict so list items stay visually
        # distinct from one another (no key lines bleeding across items).
        lines = [f"{prefix}["]
        for v in value:
            if isinstance(v, dict):
                lines.extend(inline_dict(v, indent + 1))
            else:
                lines.append(convert_any(v, indent + 1))
        lines.append(f"{prefix}]")
        return "\n".join(lines)

    else:
        # Primitive at arbitrary nesting depth
        return f"{prefix}{format_value(value)}"


def json_to_loon(data):
    """Top-level entry point: convert parsed JSON *data* to a LOON string."""
    return convert_any(data)


# ------------------------
# SIZE / TOKEN REPORT
# Printed after conversion so the caller can see how much was saved.
# Byte counts use UTF-8 encoding; token counts use count_tokens().
# Green = smaller (saved), Red = larger (grew).
# ------------------------

def print_size_stats(input_text, output_text):
    """Print a before/after size report (bytes and tokens) to stdout."""
    in_bytes  = len(input_text.encode("utf-8"))
    out_bytes = len(output_text.encode("utf-8"))

    in_tokens  = count_tokens(input_text)
    out_tokens = count_tokens(output_text)

    byte_diff  = out_bytes  - in_bytes
    token_diff = out_tokens - in_tokens

    byte_pct  = (byte_diff  / in_bytes  * 100) if in_bytes  else 0
    token_pct = (token_diff / in_tokens * 100) if in_tokens else 0

    def sign(x):
        return "+" if x > 0 else ""

    print(color("=== SIZE REPORT ===", BOLD))
    print(
        f"Bytes : {color(str(in_bytes), BLUE)} -> {color(str(out_bytes), CYAN)} "
        f"({color(sign(byte_diff)+str(byte_diff), GREEN if byte_diff < 0 else RED)}"
        f" {sign(byte_pct)+f'{byte_pct:.2f}%'} )"
    )
    print(
        f"Tokens: {color(str(in_tokens), BLUE)} -> {color(str(out_tokens), CYAN)} "
        f"({color(sign(token_diff)+str(token_diff), GREEN if token_diff < 0 else RED)}"
        f" {sign(token_pct)+f'{token_pct:.2f}%'} )"
    )


# ------------------------
# IO HELPERS
# ------------------------

def read_input(path):
    """Read raw JSON text from *path*, or from stdin if *path* is None."""
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


# ------------------------
# MAIN
# ------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert JSON to compact LOON format."
    )
    parser.add_argument("input",  nargs="?",       help="Input JSON file (default: stdin)")
    parser.add_argument("-o", "--output",           help="Output LOON file (default: stdout)")
    args = parser.parse_args()

    try:
        raw_input = read_input(args.input)
        data      = json.loads(raw_input)
        result    = json_to_loon(data)

        write_output(args.output, result)
        print_size_stats(raw_input, result)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
