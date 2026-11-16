"""docs/reference/commands.md against the two command line programs."""
import re

import typer.main

from steward import cli as steward_cli
from steward_gateway import cli as gateway_cli
from tests.public_docs import ROOT


def leaves(app) -> set[str]:
    """Every runnable command path of a typer app: "serve", "book create", "advisor pair" (click groups walked).

    Walks `.commands` rather than testing for click.Group: typer vendors its own click, so its groups are not
    click.Group instances."""
    def walk(command, path: str):
        subs = getattr(command, "commands", None)
        if subs is None:
            yield path
        else:
            for name, sub in subs.items():
                yield from walk(sub, f"{path} {name}".strip())
    return set(walk(typer.main.get_command(app), ""))


def test_the_walk_finds_the_nested_commands():
    found = leaves(steward_cli.app)
    assert {"serve", "book create", "advisor pair"} <= found
    assert "" not in found | leaves(gateway_cli.app)


def test_every_command_has_a_heading_and_every_heading_is_a_command():
    text = (ROOT / "docs/reference/commands.md").read_text()
    shown = set(re.findall(r"^### `(steward(?:-gateway)? [a-z][a-z -]*)`", text, re.M))
    assert shown == ({f"steward {c}" for c in leaves(steward_cli.app)}
                     | {f"steward-gateway {c}" for c in leaves(gateway_cli.app)})
