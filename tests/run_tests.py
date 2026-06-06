#!/usr/bin/env python3
"""Run file-based LOON conversion tests."""

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import to_json
import to_loon

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"


def color(text, code):
    return f"{code}{text}{RESET}"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_loon(path):
    return path.read_text(encoding="utf-8").strip()


def fixture_pairs():
    pairs = []
    for json_path in sorted(TEST_DIR.glob("*.json")):
        loon_path = json_path.with_suffix(".loon")
        if not loon_path.exists():
            raise AssertionError(f"Missing LOON fixture for {json_path.name}")
        pairs.append((json_path, loon_path))
    if not pairs:
        raise AssertionError("No JSON/LOON fixture pairs found")
    return pairs


def fixture_stats():
    pairs = fixture_pairs()
    json_bytes = sum(json_path.stat().st_size for json_path, _ in pairs)
    loon_bytes = sum(loon_path.stat().st_size for _, loon_path in pairs)
    return {
        "pairs": len(pairs),
        "json_bytes": json_bytes,
        "loon_bytes": loon_bytes,
        "saved_bytes": json_bytes - loon_bytes,
    }


class LOONFixtureTests(unittest.TestCase):
    def test_loon_fixtures_parse_to_matching_json(self):
        for json_path, loon_path in fixture_pairs():
            with self.subTest(fixture=loon_path.name):
                expected = load_json(json_path)
                parsed = to_json.loon_to_json_data(load_loon(loon_path))
                self.assertEqual(parsed, expected)

    def test_json_fixtures_convert_and_round_trip(self):
        for json_path, _ in fixture_pairs():
            with self.subTest(fixture=json_path.name):
                expected = load_json(json_path)
                loon_text = to_loon.json_to_loon(expected)
                parsed = to_json.loon_to_json_data(loon_text)
                self.assertEqual(parsed, expected)

    def test_json_to_loon_matches_canonical_fixture(self):
        for json_path, loon_path in fixture_pairs():
            with self.subTest(fixture=json_path.name):
                data = load_json(json_path)
                self.assertEqual(to_loon.json_to_loon(data), load_loon(loon_path))

    def test_root_sample_files_round_trip(self):
        sample_json = load_json(ROOT / "test.json")
        sample_loon = load_loon(ROOT / "test.loon")
        self.assertEqual(to_json.loon_to_json_data(sample_loon), sample_json)
        self.assertEqual(
            to_json.loon_to_json_data(to_loon.json_to_loon(sample_json)),
            sample_json,
        )

    def test_parse_errors(self):
        bad_inputs = [
            "",
            "value: [1,",
            "rows(a, b):\n  1",
            "[\n1\n]",
            '"bad string: "unterminated',
        ]
        for loon_text in bad_inputs:
            with self.subTest(loon_text=loon_text):
                with self.assertRaises(to_json.LOONParseError):
                    to_json.loon_to_json_data(loon_text)


class ColorTestResult(unittest.TextTestResult):
    def getDescription(self, test):
        description = super().getDescription(test)
        return description.replace(" (__main__.LOONFixtureTests)", "")

    def startTest(self, test):
        unittest.TestResult.startTest(self, test)
        if self.showAll:
            self.stream.write(f"{color('RUN ', BLUE)} {self.getDescription(test)} ... ")
            self.stream.flush()

    def addSuccess(self, test):
        unittest.TestResult.addSuccess(self, test)
        if self.showAll:
            self.stream.writeln(color("ok", GREEN))
        elif self.dots:
            self.stream.write(color(".", GREEN))
            self.stream.flush()

    def addError(self, test, err):
        unittest.TestResult.addError(self, test, err)
        if self.showAll:
            self.stream.writeln(color("ERROR", RED))
        elif self.dots:
            self.stream.write(color("E", RED))
            self.stream.flush()

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        if self.showAll:
            self.stream.writeln(color("FAIL", RED))
        elif self.dots:
            self.stream.write(color("F", RED))
            self.stream.flush()

    def addSkip(self, test, reason):
        unittest.TestResult.addSkip(self, test, reason)
        if self.showAll:
            self.stream.writeln(color(f"skipped: {reason}", YELLOW))
        elif self.dots:
            self.stream.write(color("s", YELLOW))
            self.stream.flush()


class ColorTestRunner(unittest.TextTestRunner):
    resultclass = ColorTestResult

    def run(self, test):
        start = time.perf_counter()
        stats = fixture_stats()

        self.stream.writeln(color("LOON test suite", BOLD + CYAN))
        self.stream.writeln(
            f"{color('Fixtures', BOLD)}: {stats['pairs']} JSON/LOON pairs, "
            f"{stats['json_bytes']} JSON bytes, {stats['loon_bytes']} LOON bytes"
        )
        self.stream.writeln("")

        result = super().run(test)
        elapsed = time.perf_counter() - start

        passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
        status = "PASS" if result.wasSuccessful() else "FAIL"
        status_color = GREEN if result.wasSuccessful() else RED

        self.stream.writeln("")
        self.stream.writeln(color("Summary", BOLD))
        self.stream.writeln(f"Status     : {color(status, BOLD + status_color)}")
        self.stream.writeln(f"Tests      : {result.testsRun}")
        self.stream.writeln(f"Passed     : {color(str(passed), GREEN)}")
        self.stream.writeln(f"Failures   : {color(str(len(result.failures)), RED if result.failures else GREEN)}")
        self.stream.writeln(f"Errors     : {color(str(len(result.errors)), RED if result.errors else GREEN)}")
        self.stream.writeln(f"Skipped    : {color(str(len(result.skipped)), YELLOW if result.skipped else GREEN)}")
        self.stream.writeln(f"Fixtures   : {stats['pairs']} pairs")
        self.stream.writeln(
            f"Size       : JSON {stats['json_bytes']} bytes -> "
            f"LOON {stats['loon_bytes']} bytes "
            f"({color(str(stats['saved_bytes']) + ' bytes saved', GREEN if stats['saved_bytes'] >= 0 else RED)})"
        )
        self.stream.writeln(f"Duration   : {elapsed:.3f}s")
        return result


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LOONFixtureTests)
    runner = ColorTestRunner(verbosity=2)
    outcome = runner.run(suite)
    sys.exit(0 if outcome.wasSuccessful() else 1)
