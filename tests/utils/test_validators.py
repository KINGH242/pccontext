import pytest

from pccontext.utils.validators import check_ada_handle_format


@pytest.mark.parametrize(
    "handle, expected",
    [
        ("$validhandle", "$validhandle"),  # happy path
        ("$valid.handle", "$valid.handle"),  # happy path with dot
        ("$valid-handle", "$valid-handle"),  # happy path with hyphen
        ("$valid_handle", "$valid_handle"),  # happy path with underscore
        (
            "$validhandle@subhandle",
            "$validhandle@subhandle",
        ),  # happy path with subhandle
        (
            "$valid.handle@sub.handle",
            "$valid.handle@sub.handle",
        ),  # happy path with dot in subhandle
        (
            "$valid-handle@sub-handle",
            "$valid-handle@sub-handle",
        ),  # happy path with hyphen in subhandle
        (
            "$valid_handle@sub_handle",
            "$valid_handle@sub_handle",
        ),  # happy path with underscore in subhandle
        ("$a", "$a"),  # edge case: minimum length handle
        ("$a@b", "$a@b"),  # edge case: minimum length handle and subhandle
        ("$" + "a" * 15, "$" + "a" * 15),  # edge case: maximum length handle
        (
            "$" + "a" * 15 + "@" + "b" * 15,
            "$" + "a" * 15 + "@" + "b" * 15,
        ),  # edge case: maximum length handle and subhandle
    ],
    ids=[
        "valid handle",
        "valid handle with dot",
        "valid handle with hyphen",
        "valid handle with underscore",
        "valid handle with subhandle",
        "valid handle with dot in subhandle",
        "valid handle with hyphen in subhandle",
        "valid handle with underscore in subhandle",
        "minimum length handle",
        "minimum length handle and subhandle",
        "maximum length handle",
        "maximum length handle and subhandle",
    ],
)
def test_check_ada_handle_format_valid(handle, expected):
    # Act
    result = check_ada_handle_format(handle)

    # Assert
    assert result == expected


@pytest.mark.parametrize(
    "handle",
    [
        None,  # edge case: None input
        "",  # error case: empty string
        "validhandle",  # error case: missing $
        "$invalid handle",  # error case: space in handle
        "$invalid@sub handle",  # error case: space in subhandle
        "$invalidhandle@",  # error case: trailing @
        "$invalidhandle@subhandle@",  # error case: trailing @ after subhandle
        "$" + "a" * 16,  # error case: handle too long
        "$validhandle@" + "b" * 16,  # error case: subhandle too long
        "$invalid!handle",  # error case: invalid character in handle
        "$validhandle@sub!handle",  # error case: invalid character in subhandle
    ],
    ids=[
        "None input",
        "empty string",
        "missing $",
        "space in handle",
        "space in subhandle",
        "trailing @",
        "trailing @ after subhandle",
        "handle too long",
        "subhandle too long",
        "invalid character in handle",
        "invalid character in subhandle",
    ],
)
def test_check_ada_handle_format_invalid(handle):
    # Act & Assert
    with pytest.raises(ValueError):
        check_ada_handle_format(handle)
