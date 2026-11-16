"""Driving the batch import from tests (import/export spec, API): stage files, preview, commit."""
from __future__ import annotations

from urllib.parse import quote

from tests.bank_files import read


def stage(client, name: str, raw: bytes | None = None, batch: str | None = None, slug: str = "ours"):
    url = f"/api/b/{slug}/import/files" + (f"?batch={batch}" if batch else "")
    return client.post(url, content=read(name) if raw is None else raw,
                       headers={"content-type": "application/octet-stream", "x-filename": quote(name)})


def file_choice(entry: dict, account_id: int, negate: bool = False, include=()) -> dict:
    """The preview body's line for one staged entry: a new layout is confirmed as guessed, with the sign given here
    when the file couldn't say, and the date format its question's first option when it was asked."""
    layout = None
    if entry["state"] == "new":
        lay = entry["layout"]
        layout = {"mapping": lay["mapping"], "negate": negate if lay["negate"] is None else lay["negate"],
                  "date_format": lay["date_format"] or lay["date_question"]["options"][0]["format"]}
    return {"token": entry["token"], "account_id": account_id, "layout": layout, "include": list(include)}


def preview(client, batch: str, files: list[dict], simplefin_include=(), slug: str = "ours"):
    return client.post(f"/api/b/{slug}/import/batch/preview",
                       json={"batch": batch, "files": files, "simplefin_include": list(simplefin_include)})


def import_file(client, name: str, account_id: int, raw: bytes | None = None, slug: str = "ours", negate: bool = False,
                include_same: bool = False, simplefin: bool = False):
    """Stage one file, preview it into one account and commit; returns the commit's response. include_same imports the
    rows that look the same (Look's Import anyway); simplefin imports the rows SimpleFIN already has (Import these too)."""
    r = stage(client, name, raw, slug=slug)
    assert r.status_code == 201, r.text
    batch = r.json()["batch"]
    files = [file_choice(e, account_id, negate) for e in r.json()["files"] if e["token"]]
    sf = [account_id] if simplefin else []
    p = preview(client, batch, files, sf, slug).json()
    if include_same:
        rows: dict[str, list[int]] = {}
        for s in p["look"]["same"]:
            rows.setdefault(s["token"], []).append(s["row"])
        files = [{**f, "include": rows.get(f["token"], [])} for f in files]
        p = preview(client, batch, files, sf, slug).json()
    return client.post(f"/api/b/{slug}/import/batch/commit",
                       json={"batch": batch, "files": files, "simplefin_include": sf, "digest": p["digest"]})
