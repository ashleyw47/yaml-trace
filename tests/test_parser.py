"""Tests for the hand-rolled YAML subset parser.

Line-number tracking is the point of this tool, so most tests check
both the value and the .lines mapping, not just the value.
"""

from __future__ import annotations

import unittest

from yamltrace.parser import YamlError, YList, YMap, parse


class ScalarTests(unittest.TestCase):
    def scalar(self, literal):
        tree = parse("x: " + literal + "\n")
        return tree["x"]

    def test_null_spellings(self):
        for literal in ("~", "null", "Null", "NULL", ""):
            self.assertIsNone(self.scalar(literal))

    def test_bool_spellings(self):
        for literal in ("true", "True", "TRUE"):
            self.assertIs(self.scalar(literal), True)
        for literal in ("false", "False", "FALSE"):
            self.assertIs(self.scalar(literal), False)

    def test_integers_and_floats(self):
        self.assertEqual(self.scalar("42"), 42)
        self.assertEqual(self.scalar("-7"), -7)
        self.assertEqual(self.scalar("3.14"), 3.14)
        self.assertEqual(self.scalar("-0.5"), -0.5)

    def test_non_numeric_falls_back_to_string(self):
        self.assertEqual(self.scalar("1.2.3"), "1.2.3")
        self.assertEqual(self.scalar("not-a-number"), "not-a-number")

    def test_single_quoted_string_is_literal(self):
        self.assertEqual(self.scalar("'true'"), "true")
        self.assertEqual(self.scalar("'42'"), "42")

    def test_single_quoted_escape_is_doubled_quote(self):
        self.assertEqual(self.scalar("'it''s'"), "it's")

    def test_double_quote_escape_sequences(self):
        self.assertEqual(self.scalar('"a\\nb"'), "a\nb")
        self.assertEqual(self.scalar('"a\\tb"'), "a\tb")
        self.assertEqual(self.scalar('"a\\rb"'), "a\rb")
        self.assertEqual(self.scalar('"a\\"b"'), 'a"b')
        self.assertEqual(self.scalar('"a\\\\b"'), "a\\b")

    def test_double_quote_unrecognized_escape_kept_literal(self):
        self.assertEqual(self.scalar('"a\\qb"'), "a\\qb")

    def test_double_quoted_string_with_comma_and_colon(self):
        self.assertEqual(self.scalar('"hello, world: still one value"'),
                          "hello, world: still one value")

    def test_flow_collections_are_opaque_strings(self):
        # Flow collections aren't parsed yet (see README); they come back
        # as plain scalar text rather than a list/dict or an error.
        self.assertEqual(self.scalar("[1, 2, 3]"), "[1, 2, 3]")
        self.assertEqual(self.scalar("{a: 1, b: 2}"), "{a: 1, b: 2}")


class MappingTests(unittest.TestCase):
    def test_flat_mapping(self):
        tree = parse("a: 1\nb: two\n")
        self.assertEqual(tree, {"a": 1, "b": "two"})
        self.assertEqual(tree.lines, {"a": 1, "b": 2})

    def test_nested_mapping(self):
        text = "database:\n  host: localhost\n  port: 5432\n"
        tree = parse(text)
        self.assertEqual(tree, {"database": {"host": "localhost", "port": 5432}})
        self.assertEqual(tree.lines, {"database": 1})
        self.assertEqual(tree["database"].lines, {"host": 2, "port": 3})

    def test_quoted_key_containing_colon(self):
        tree = parse('"a:b": 1\n')
        self.assertEqual(tree, {"a:b": 1})

    def test_blank_and_comment_lines_do_not_shift_line_numbers(self):
        text = "a: 1\n\n# just a comment\nb: 2\n"
        tree = parse(text)
        self.assertEqual(tree, {"a": 1, "b": 2})
        self.assertEqual(tree.lines, {"a": 1, "b": 4})

    def test_comment_stripped_outside_quotes_only(self):
        text = 'a: 1 # comment\nb: "text # not a comment"\n'
        tree = parse(text)
        self.assertEqual(tree, {"a": 1, "b": "text # not a comment"})

    def test_document_markers_are_skipped(self):
        tree = parse("---\na: 1\n...\n")
        self.assertEqual(tree, {"a": 1})
        self.assertEqual(tree.lines, {"a": 2})

    def test_empty_input_is_empty_mapping(self):
        tree = parse("")
        self.assertEqual(tree, {})
        self.assertIsInstance(tree, YMap)

    def test_missing_colon_raises(self):
        with self.assertRaises(YamlError) as ctx:
            parse("just some text\n")
        self.assertEqual(ctx.exception.lineno, 1)

    def test_tab_in_indentation_raises(self):
        with self.assertRaises(YamlError) as ctx:
            parse("a:\n\tb: 1\n")
        self.assertEqual(ctx.exception.lineno, 2)

    def test_error_message_includes_filename_and_line(self):
        with self.assertRaises(YamlError) as ctx:
            parse("a:\n\tb: 1\n", filename="staging.yaml")
        self.assertEqual(str(ctx.exception), "staging.yaml:2: tabs are not allowed in indentation")


class SequenceTests(unittest.TestCase):
    def test_scalar_list(self):
        tree = parse("items:\n  - a\n  - b\n  - c\n")
        self.assertEqual(tree["items"], ["a", "b", "c"])
        self.assertIsInstance(tree["items"], YList)

    def test_list_of_mappings_shorthand(self):
        text = "servers:\n  - host: a\n    port: 1\n  - host: b\n    port: 2\n"
        tree = parse(text)
        servers = tree["servers"]
        self.assertEqual(
            servers,
            [{"host": "a", "port": 1}, {"host": "b", "port": 2}],
        )
        self.assertEqual(servers[0].lines, {"host": 2, "port": 3})
        self.assertEqual(servers[1].lines, {"host": 4, "port": 5})

    def test_dash_alone_holds_nested_mapping(self):
        text = "items:\n  -\n    a: 1\n    b: 2\n"
        tree = parse(text)
        self.assertEqual(tree["items"], [{"a": 1, "b": 2}])

    def test_empty_dash_entry_without_nested_block_is_none(self):
        text = "items:\n  - \n  - x\n"
        tree = parse(text)
        self.assertEqual(tree["items"], [None, "x"])

    def test_malformed_entry_continuation_raises(self):
        text = "items:\n  - host: a\n    justtext\n"
        with self.assertRaises(YamlError) as ctx:
            parse(text)
        self.assertEqual(ctx.exception.lineno, 3)


if __name__ == "__main__":
    unittest.main()
