from app.llm import _is_safe_select, _extract_sql


def test_allows_simple_select():
    assert _is_safe_select("SELECT COUNT(*) FROM data WHERE status = 'Open'")


def test_allows_with_clause():
    assert _is_safe_select("WITH t AS (SELECT * FROM data) SELECT COUNT(*) FROM t")


def test_allows_forbidden_word_inside_quoted_value():
    assert _is_safe_select("SELECT * FROM data WHERE issue_summary LIKE '%update%'")


def test_blocks_drop():
    assert not _is_safe_select("DROP TABLE data")


def test_blocks_delete():
    assert not _is_safe_select("DELETE FROM data")


def test_blocks_second_statement():
    assert not _is_safe_select("SELECT 1; DELETE FROM data")


def test_blocks_comment():
    assert not _is_safe_select("SELECT * FROM data -- hidden")


def test_blocks_pragma():
    assert not _is_safe_select("PRAGMA table_info(data)")


def test_extract_sql_strips_markdown_fence():
    assert _extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"