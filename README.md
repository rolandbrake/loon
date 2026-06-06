<p align="center">
  <img src="loon.png" alt="LOON logo" width="240">
  <br>
  <strong>Lightweight Object Outline Notation</strong>
</p>

# LOON

**LOON** means **Lightweight Object Outline Notation**.

LOON is a compact, indentation-based notation for JSON-compatible data. It keeps
JSON's data model, objects, arrays, strings, numbers, booleans, and null, but
removes much of the repeated punctuation when the structure is already clear
from indentation.

This repository includes:

- `to_loon.py`: convert JSON to LOON
- `to_json.py`: convert LOON back to JSON
- `tests/run_tests.py`: run the fixture-based test suite
- `tests/*.json` and `tests/*.loon`: canonical syntax examples

## Quick Start

Convert JSON to LOON:

```powershell
python .\to_loon.py .\test.json -o .\test.loon
```

Convert LOON back to JSON:

```powershell
python .\to_json.py .\test.loon -o .\output.json
```

Read from stdin:

```powershell
Get-Content .\test.json | python .\to_loon.py
Get-Content .\test.loon | python .\to_json.py
```

Write compact JSON output:

```powershell
python .\to_json.py .\test.loon --compact
```

Run the tests:

```powershell
python .\tests\run_tests.py
```

## Basic Syntax

LOON uses two spaces per indentation level.

JSON:

```json
{
  "name": "LOON",
  "active": true,
  "count": 3,
  "missing": null
}
```

LOON:

```loon
name: "LOON"
active: true
count: 3
missing: null
```

## Values

LOON supports the same JSON value types:

- strings: `"hello"`
- numbers: `42`, `-3`, `2.5`
- booleans: `true`, `false`
- null: `null`
- objects
- arrays

Strings use JSON-style escaping:

```loon
message: "quote: \" slash: \\ newline:\n tab:\t"
```

## Object Keys

Simple identifier-like keys can be written bare:

```loon
name: "Ada"
age: 36
```

Keys with spaces, punctuation, empty names, or escape characters are quoted:

```loon
"": "empty key"
"first name": "Ada"
"a:b": "colon"
"line\nkey": "line value"
```

## Nested Objects

Nested objects are written by ending the parent key with `:` and indenting the
child fields:

```loon
widget:
  debug: "on"
  window:
    title: "Sample"
    width: 500
    height: 500
```

Empty objects are explicit:

```loon
meta: {}
```

## Arrays

Primitive arrays can be written inline:

```loon
values:
  [1, "two", true, false, null]
```

Mixed or nested arrays use a block form:

```loon
items:
  [
    1
    {name: "flat", ok: true}
    {
      name: "deep"
      meta:
        rank: 2
    }
    [1, 2, 3]
    []
  ]
```

Empty arrays are explicit:

```loon
items:
  []
```

## Inline Objects

Flat objects inside arrays can be written on one line:

```loon
{name: "Ada", age: 36, active: true}
```

If an object contains nested values, use the braced block form:

```loon
{
  name: "deep"
  meta:
    rank: 2
}
```

## Tables

LOON can compact arrays of objects into a table when every row has the same keys
and every cell is a primitive value.

JSON:

```json
{
  "rows": [
    {"name": "Ada", "age": 36, "active": true},
    {"name": "Linus", "age": 55, "active": false}
  ]
}
```

LOON:

```loon
rows(name, age, active):
  "Ada", 36, true
  "Linus", 55, false
```

Table columns are quoted when needed:

```loon
rows("first name", "a:b"):
  "Ada", 1
  "Grace", 2
```

Root-level tables are also supported:

```loon
(name, age):
  "Ada", 36
  "Grace", 85
```

## Script Reference

### `to_loon.py`

Convert JSON into LOON:

```powershell
python .\to_loon.py [input.json] [-o output.loon]
```

If no input file is passed, the script reads JSON from stdin. If no output file
is passed, it prints LOON to stdout.

After conversion, it prints a size report with byte and estimated token counts.

### `to_json.py`

Convert LOON into JSON:

```powershell
python .\to_json.py [input.loon] [-o output.json] [--compact]
```

If no input file is passed, the script reads LOON from stdin. If no output file
is passed, it prints JSON to stdout.

Use `--compact` to write minified JSON instead of pretty-printed JSON.

## Test Suite

The tests are file-based. Every `tests/*.json` fixture has a matching
`tests/*.loon` fixture with the same name.

Run:

```powershell
python .\tests\run_tests.py
```

The test runner checks:

- every `.loon` fixture parses to the matching `.json`
- every `.json` fixture converts to LOON and round-trips back to the same data
- generated LOON matches the canonical `.loon` fixture
- root sample files round-trip
- invalid LOON inputs fail with parser errors

The runner prints colored results and summary stats, including fixture count,
test count, pass/fail totals, byte savings, and duration.

## Format Notes

- LOON is designed for JSON-compatible data.
- Indentation is structural and uses two spaces per level.
- Strings and quoted keys use JSON escaping.
- Bare keys are allowed only for identifier-like names.
- Tables are used only for uniform arrays of primitive-valued objects.
- Non-finite numbers such as `NaN` or `Infinity` are not valid JSON values and
  are not representable in LOON.
