# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for LlamaParse markdown table normalization."""

from nap_tool.extractor.tools.llamaparse_tool import markdown_tables


def test_markdown_tables_extracts_multiple_tables() -> None:
    """Markdown table separator rows are removed from separate grids."""

    markdown = """Text

| A | B |
| --- | :---: |
| 1 | 2 |

More text

| C | D |
| --- | --- |
| 3 | 4 |
"""

    assert markdown_tables(markdown) == [
        [["A", "B"], ["1", "2"]],
        [["C", "D"], ["3", "4"]],
    ]
