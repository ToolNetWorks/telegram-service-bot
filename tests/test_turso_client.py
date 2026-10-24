import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from turso_client import (TursoConnection, TursoRow, TursoCursor, TursoError,
                          split_sql, _encode_arg, _decode_value)


class TursoClientUnitTests(unittest.TestCase):
    def test_split_sql_respects_strings_and_comments(self):
        script = """
            -- leading comment; with semicolon
            CREATE TABLE t (id INTEGER); /* block; comment */
            INSERT INTO t VALUES ('a;b');
            INSERT INTO t VALUES ("c;d");
            SELECT 'it''s; fine';
        """
        statements = split_sql(script)
        self.assertEqual(len(statements), 4)
        self.assertIn("'a;b'", statements[1])
        self.assertIn('"c;d"', statements[2])
        self.assertIn("it''s; fine", statements[3])

    def test_row_supports_name_and_index(self):
        row = TursoRow(("id", "balance"), (7, 1234))
        self.assertEqual(row["id"], 7)
        self.assertEqual(row[1], 1234)
        self.assertEqual(row.keys(), ["id", "balance"])
        self.assertEqual(tuple(row), (7, 1234))
        with self.assertRaises(KeyError):
            _ = row["missing"]

    def test_cursor_fetch(self):
        cursor = TursoCursor(("id",), [(1,), (2,)], 2, 2)
        self.assertEqual(cursor.fetchone()["id"], 1)
        self.assertEqual([row[0] for row in cursor.fetchall()], [1, 2])
        self.assertEqual(cursor.rowcount, 2)
        self.assertEqual(cursor.lastrowid, 2)

    def test_value_round_trip(self):
        self.assertEqual(_decode_value(_encode_arg(None)), None)
        self.assertEqual(_decode_value(_encode_arg(True)), 1)
        self.assertEqual(_decode_value(_encode_arg(42)), 42)
        self.assertAlmostEqual(_decode_value(_encode_arg(1.5)), 1.5)
        self.assertEqual(_decode_value(_encode_arg("xin chào")), "xin chào")
        self.assertEqual(_decode_value(_encode_arg(b"\x00\xff")), b"\x00\xff")

    def test_connection_requires_turso_config(self):
        with self.assertRaises(TursoError):
            TursoConnection("", "")
        with self.assertRaises(TursoError):
            TursoConnection("ftp://example.invalid", "token")


if __name__ == "__main__":
    unittest.main()
