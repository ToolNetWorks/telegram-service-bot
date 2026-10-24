"""Minimal Turso / libSQL client over the Hrana v2 HTTP protocol.

The bot uses only the Python standard library.  ``libsql_client``'s HTTP
transport does not support interactive transactions, so this module speaks
the Hrana v2 pipeline protocol directly and keeps the server-side ``baton``
between requests.  That gives the bot real ``BEGIN IMMEDIATE`` / ``COMMIT``
/ ``ROLLBACK`` semantics for wallet and order safety.

Security: the auth token and database URL are never written to logs or to
exception messages.

Environment:
    TURSO_URL    libsql://... or https://...
    TURSO_TOKEN  database auth token
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

LOG = logging.getLogger("servicebot.turso")

_RETRYABLE_HTTP = {429, 500, 502, 503, 504}
_READ_PREFIXES = ("SELECT", "PRAGMA", "EXPLAIN", "WITH")


class TursoError(RuntimeError):
    """Turso request or SQL error.  Never contains the token."""

    def __init__(self, message: str, code=None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class TursoRow:
    """Row that supports both ``row[0]`` and ``row["column"]`` access."""

    __slots__ = ("_columns", "_index", "_values")

    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._index = {name: idx for idx, name in enumerate(self._columns)}
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._index[key]]
            except KeyError:
                raise KeyError(key) from None
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return list(self._columns)

    def __eq__(self, other):
        if isinstance(other, TursoRow):
            return self._values == other._values
        if isinstance(other, (tuple, list)):
            return self._values == tuple(other)
        return NotImplemented

    def __repr__(self):
        return f"TursoRow({dict(zip(self._columns, self._values))!r})"


class TursoCursor:
    """Small sqlite3.Cursor-compatible surface used by db.py."""

    def __init__(self, columns=(), rows=(), rowcount: int = 0, lastrowid=None):
        self._columns = tuple(columns)
        self._rows = [TursoRow(self._columns, row) for row in rows]
        self.rowcount = int(rowcount or 0)
        self.lastrowid = int(lastrowid) if lastrowid is not None else None
        self.description = (
            tuple((name, None, None, None, None, None, None) for name in self._columns)
            if self._columns else None
        )

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)


def _encode_arg(value):
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    raise TypeError(f"Unsupported SQLite parameter type: {type(value).__name__}")


def _decode_value(value):
    kind = value.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(value["value"])
    if kind == "float":
        return float(value["value"])
    if kind == "text":
        return value["value"]
    if kind == "blob":
        return base64.b64decode(value["base64"])
    raise TursoError(f"Unsupported Turso value type: {kind}")


def split_sql(script: str):
    """Split a SQL script on semicolons, respecting strings and comments."""
    statements = []
    buffer = []
    quote = None
    i = 0
    size = len(script)
    while i < size:
        char = script[i]
        if quote is not None:
            buffer.append(char)
            if char == quote:
                if i + 1 < size and script[i + 1] == quote:
                    buffer.append(script[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if char in ("'", '"', "`"):
            quote = char
            buffer.append(char)
            i += 1
            continue
        if char == "-" and i + 1 < size and script[i + 1] == "-":
            while i < size and script[i] not in "\r\n":
                i += 1
            buffer.append("\n")
            continue
        if char == "/" and i + 1 < size and script[i + 1] == "*":
            i += 2
            while i + 1 < size and not (script[i] == "*" and script[i + 1] == "/"):
                i += 1
            i = min(size, i + 2)
            buffer.append(" ")
            continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            i += 1
            continue
        buffer.append(char)
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _is_begin(sql: str) -> bool:
    parts = sql.strip().upper().split()
    return bool(parts) and parts[0] == "BEGIN"


def _is_end(sql: str) -> bool:
    parts = sql.strip().upper().split()
    return bool(parts) and parts[0] in ("COMMIT", "END", "ROLLBACK")


def _is_read(sql: str) -> bool:
    parts = sql.lstrip().upper().split(None, 1)
    return bool(parts) and parts[0] in _READ_PREFIXES


class TursoConnection:
    """sqlite3.Connection-like adapter backed by Turso Hrana v2 over HTTPS."""

    def __init__(self, url: str, token: str, timeout: float = 30.0):
        if not url or not token:
            raise TursoError("TURSO_URL và TURSO_TOKEN là bắt buộc")
        parsed = urllib.parse.urlsplit(url.strip())
        if parsed.scheme == "libsql":
            parsed = parsed._replace(scheme="https")
        if parsed.scheme not in ("http", "https"):
            raise TursoError("TURSO_URL phải dùng libsql:// hoặc https://")
        base = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "")
        )
        self._endpoint = base + "/v2/pipeline"
        self._token = token
        self._timeout = float(timeout)
        self._baton = None
        self._closed = False
        self.ping()

    # ------------------------------------------------------------------ HTTP
    def _pipeline(self, requests, baton=None, retry: bool = False):
        body = {"requests": requests}
        if baton:
            body["baton"] = baton
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        attempts = 2 if retry else 1
        last_error = None
        for attempt in range(attempts):
            request = urllib.request.Request(
                self._endpoint, data=payload, headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise TursoError(
                        f"Turso từ chối xác thực (HTTP {exc.code}); kiểm tra TURSO_TOKEN",
                        code=exc.code,
                    ) from None
                message = f"Turso HTTP {exc.code}"
                if exc.code in _RETRYABLE_HTTP and attempt + 1 < attempts:
                    last_error = TursoError(message, code=exc.code, retryable=True)
                    time.sleep(0.4)
                    continue
                raise TursoError(message, code=exc.code,
                                 retryable=exc.code in _RETRYABLE_HTTP) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                message = f"Turso lỗi kết nối: {reason}"
                if attempt + 1 < attempts and retry:
                    last_error = TursoError(message, retryable=True)
                    time.sleep(0.4)
                    continue
                raise TursoError(message, retryable=True) from None
            except json.JSONDecodeError:
                raise TursoError("Turso trả về dữ liệu không hợp lệ") from None
        raise last_error or TursoError("Turso không phản hồi", retryable=True)

    def _run(self, sql, params, baton, want_rows: bool, retry: bool):
        statement = {
            "sql": sql,
            "args": [_encode_arg(value) for value in (params or ())],
            "want_rows": want_rows,
        }
        response = self._pipeline(
            [{"type": "execute", "stmt": statement}], baton=baton, retry=retry
        )
        results = response.get("results") or []
        if not results:
            raise TursoError("Turso không trả về kết quả")
        result = results[0]
        baton_out = response.get("baton")
        if result.get("type") != "ok":
            error = result.get("error") or {}
            return None, baton_out, {
                "message": error.get("message") or "Turso SQL error",
                "code": error.get("code"),
            }
        payload = result.get("response") or {}
        if payload.get("type") != "execute":
            return None, baton_out, {
                "message": "Turso trả về loại kết quả không mong đợi",
                "code": None,
            }
        return payload.get("result") or {}, baton_out, None

    # ------------------------------------------------------------- sqlite API
    def execute(self, sql: str, params=()):
        if self._closed:
            raise TursoError("Kết nối Turso đã đóng")
        clean = sql.strip()
        if not clean:
            return TursoCursor()
        if _is_begin(clean):
            if self._baton is not None:
                raise TursoError("Giao dịch Turso đang mở")
            result, baton, error = self._run(clean, (), None, False, False)
            if error:
                raise TursoError(error["message"], code=error["code"])
            if not baton:
                raise TursoError("Turso không mở được giao dịch")
            self._baton = baton
            return TursoCursor()
        if _is_end(clean):
            if self._baton is None:
                return TursoCursor()
            baton = self._baton
            self._baton = None
            result, _, error = self._run(clean, (), baton, False, False)
            if error:
                raise TursoError(error["message"], code=error["code"])
            return TursoCursor()
        was_transaction = self._baton is not None
        is_read = _is_read(clean)
        result, baton, error = self._run(
            clean, params, self._baton, True, retry=is_read and not was_transaction
        )
        if was_transaction:
            # A failed statement may rotate or close the server-side stream.
            self._baton = baton
        if error:
            raise TursoError(error["message"], code=error["code"])
        if was_transaction and not baton:
            self._baton = None
            raise TursoError("Turso đã đóng giao dịch ngoài ý muốn")
        columns = [column.get("name") or "" for column in result.get("cols") or []]
        rows = [
            [_decode_value(value) for value in row]
            for row in result.get("rows") or []
        ]
        return TursoCursor(
            columns,
            rows,
            result.get("affected_row_count", 0),
            result.get("last_insert_rowid"),
        )

    def executemany(self, sql: str, seq):
        rows = list(seq)
        if not rows:
            return TursoCursor()
        if self._baton is not None:
            for params in rows:
                self.execute(sql, params)
            return TursoCursor()
        columns = []
        lastrowid = None
        rowcount = 0
        chunk_size = 100
        for start in range(0, len(rows), chunk_size):
            chunk = rows[start:start + chunk_size]
            steps = [{"stmt": {"sql": "BEGIN", "want_rows": False}}]
            for params in chunk:
                steps.append({
                    "condition": {"type": "ok", "step": len(steps) - 1},
                    "stmt": {
                        "sql": sql,
                        "args": [_encode_arg(value) for value in params],
                        "want_rows": False,
                    },
                })
            steps.append({
                "condition": {"type": "ok", "step": len(steps) - 1},
                "stmt": {"sql": "COMMIT", "want_rows": False},
            })
            steps.append({
                "condition": {
                    "type": "not",
                    "cond": {"type": "ok", "step": len(steps) - 1},
                },
                "stmt": {"sql": "ROLLBACK", "want_rows": False},
            })
            response = self._pipeline([
                {"type": "batch", "batch": {"steps": steps}}
            ], retry=False)
            results = response.get("results") or []
            if not results:
                raise TursoError("Turso không trả về kết quả batch")
            result = results[0]
            if result.get("type") != "ok":
                error = result.get("error") or {}
                raise TursoError(error.get("message") or "Turso batch error",
                                 code=error.get("code"))
            payload = result.get("response") or {}
            batch_result = payload.get("result") or {}
            errors = [error for error in batch_result.get("step_errors") or [] if error]
            if errors:
                raise TursoError(errors[0].get("message") or "Turso batch error",
                                 code=errors[0].get("code"))
            rowcount += len(chunk)
        return TursoCursor(columns, [], rowcount, lastrowid)

    def executescript(self, script: str):
        statements = split_sql(script)
        if not statements:
            return TursoCursor()
        if self._baton is not None:
            for statement in statements:
                self.execute(statement)
            return TursoCursor()
        steps = [{"stmt": {"sql": "BEGIN", "want_rows": False}}]
        for statement in statements:
            steps.append({
                "condition": {"type": "ok", "step": len(steps) - 1},
                "stmt": {"sql": statement, "want_rows": False},
            })
        steps.append({
            "condition": {"type": "ok", "step": len(steps) - 1},
            "stmt": {"sql": "COMMIT", "want_rows": False},
        })
        steps.append({
            "condition": {
                "type": "not",
                "cond": {"type": "ok", "step": len(steps) - 1},
            },
            "stmt": {"sql": "ROLLBACK", "want_rows": False},
        })
        response = self._pipeline([{"type": "batch", "batch": {"steps": steps}}],
                                  retry=False)
        results = response.get("results") or []
        if not results:
            raise TursoError("Turso không trả về kết quả schema")
        result = results[0]
        if result.get("type") != "ok":
            error = result.get("error") or {}
            raise TursoError(error.get("message") or "Turso schema error",
                             code=error.get("code"))
        batch_result = (result.get("response") or {}).get("result") or {}
        errors = [error for error in batch_result.get("step_errors") or [] if error]
        if errors:
            raise TursoError(errors[0].get("message") or "Turso schema error",
                             code=errors[0].get("code"))
        return TursoCursor()

    def ping(self):
        row = self.execute("SELECT 1").fetchone()
        return bool(row and row[0] == 1)

    def close(self):
        if self._closed:
            return
        if self._baton is not None:
            try:
                baton = self._baton
                self._baton = None
                self._run("ROLLBACK", (), baton, False, False)
            except Exception:
                LOG.debug("Không thể rollback khi đóng kết nối Turso")
        self._closed = True

    def __repr__(self):
        return "<TursoConnection (remote)>"
