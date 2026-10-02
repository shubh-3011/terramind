from app.main import _trim_incomplete_hcl, _trim_repetition_loop


def test_repetition_loop_is_cut_at_first_repeat():
    block = '# Data source\ndata "aws_iam_users" "available" {\n  filter {\n    name = "tag:Name"\n  }\n}'
    source = f'{block}\n\n{block}\n\n{block}\n'
    result, trimmed = _trim_repetition_loop(source)
    assert trimmed is True
    assert result.strip() == block.strip()


def test_non_repeating_source_is_unchanged():
    source = 'resource "a" "b" {\n  x = 1\n}\n\nresource "c" "d" {\n  y = 2\n}\n'
    result, trimmed = _trim_repetition_loop(source)
    assert trimmed is False
    assert result == source


def test_balanced_source_is_unchanged():
    source = 'resource "a" "b" {\n  x = 1\n}\n'
    result, trimmed = _trim_incomplete_hcl(source)
    assert trimmed is False
    assert result == source


def test_truncated_trailing_block_is_dropped():
    source = 'resource "a" "b" {\n  x = 1\n}\n\nresource "c" "d" {\n  y = 2\n'
    result, trimmed = _trim_incomplete_hcl(source)
    assert trimmed is True
    assert 'resource "a" "b"' in result
    assert 'resource "c" "d"' not in result
    assert result.rstrip().endswith("}")


def test_truncated_after_a_complete_resource_is_trimmed():
    source = 'resource "a" "b" {\n  x = 1\n}\n\nresource "c" "d" {\n  y = [\n    "one",\n'
    result, trimmed = _trim_incomplete_hcl(source)
    assert trimmed is True
    assert 'resource "a" "b"' in result
    assert 'resource "c" "d"' not in result


def test_braces_inside_strings_and_comments_are_ignored():
    source = 'resource "a" "b" {\n  x = "}{ # not a brace"\n  # }\n}\n'
    result, trimmed = _trim_incomplete_hcl(source)
    assert trimmed is False
    assert result == source
