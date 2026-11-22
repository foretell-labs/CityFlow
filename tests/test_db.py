"""Tests for city_flow.db.fetch_one."""

import duckdb
import pytest

from city_flow.db import fetch_one


def test_returns_first_row() -> None:
    con = duckdb.connect()
    assert fetch_one(con, "SELECT ?, 'x'", [42]) == (42, "x")


def test_raises_when_no_rows() -> None:
    con = duckdb.connect()
    with pytest.raises(ValueError, match="no rows"):
        fetch_one(con, "SELECT 1 WHERE false")
