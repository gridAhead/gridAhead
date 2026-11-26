# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""The nap-tool command line interface."""

import typer

from nap_tool.classifier.commands import classify_command, propose_app
from nap_tool.database.migrate import migrate
from nap_tool.database.upgrade import upgrade
from nap_tool.downloader.commands import discover, download, sync_identifiers
from nap_tool.extractor.commands import extract
from nap_tool.ui.commands import ui

app = typer.Typer(help="Discover, download, and extract grid extension plans.")
app.command(name="discover")(discover)
app.command(name="sync-dso-identifiers")(sync_identifiers)
app.command(name="download")(download)
app.command(name="extract")(extract)
app.command(name="migrate")(migrate)
app.command(name="upgrade")(upgrade)
app.command(name="classify")(classify_command)
app.add_typer(propose_app, name="propose")


app.command(name="ui")(ui)


if __name__ == "__main__":
    app()
