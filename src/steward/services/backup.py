"""Encrypted copies (VACUUM INTO, same key) of the directory and of every book (spec 2.7):
steward-<slug>-YYYYMMDD-HHMMSS.db and steward-directory-YYYYMMDD-HHMMSS.db, keeping the 14 newest of each. A parent
book's encrypted files folder is also mirrored into steward-<slug>-files/ (spec 3.5)."""
import filecmp
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from steward.db.engine import allow_writes

KEEP = 14
GONE_DAYS = 14
KEY_INSIDE = ("The backup folder {folder} holds the encryption key ({key}). Choose one that doesn't, so a backup alone "
              "opens nothing.")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _check(dest_dir: Path, key_path: Path | None = None) -> None:
    d = str(dest_dir)
    if not dest_dir.is_absolute() or "'" in d or '"' in d or "\0" in d:
        raise ValueError("Backup folder must be an absolute path without quote characters.")
    if key_path is not None and key_path.resolve().is_relative_to(dest_dir.resolve()):
        raise ValueError(KEY_INSIDE.format(folder=dest_dir, key=key_path))
    dest_dir.mkdir(mode=0o700, parents=True, exist_ok=True)


def _prune(dest_dir: Path, prefix: str, keep: int) -> None:
    pattern = re.compile(rf"^{re.escape(prefix)}-\d{{8}}-\d{{6}}\.db$")
    copies = sorted(p for p in dest_dir.iterdir() if pattern.match(p.name))
    for old in copies[:-keep]:
        old.unlink()


def backup_engine(engine, dest_dir: Path, prefix: str, stamp: str, keep: int = KEEP) -> Path:
    target = dest_dir / f"{prefix}-{stamp}.db"
    raw = engine.raw_connection()
    try:
        allow_writes(raw)
        # VACUUM INTO takes no bound parameters; the folder was checked by _check.
        raw.driver_connection.execute(f"VACUUM INTO '{target}'")
    finally:
        raw.close()
    os.chmod(target, 0o600)
    _prune(dest_dir, prefix, keep)
    return target


def mirror_files(src: Path, dest: Path, now: datetime | None = None) -> int:
    """Copies a book's encrypted files that the mirror doesn't have yet. A file already there with the same size and
    the same bytes is skipped; one whose bytes differ (an id reused after a restore) is copied again. A file removed in the app keeps its copy for 14 days, matching backup
    rotation (ledger ruling 2, which supersedes plan ruling 5): the first backup that finds it missing writes
    <id>.gone with the time, and a later backup after 14 days deletes both. A file that is back clears its mark."""
    now = now or datetime.now(timezone.utc)
    if not src.is_dir():
        return 0
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    copied = 0
    here = {p.name for p in src.iterdir() if p.is_file() and p.name.isdigit()}
    for name in sorted(here, key=int):
        p = src / name
        (dest / f"{name}.gone").unlink(missing_ok=True)
        target = dest / name
        if target.exists() and target.stat().st_size == p.stat().st_size and filecmp.cmp(p, target, shallow=False):
            continue
        tmp = dest / f"{name}.partial"
        shutil.copyfile(p, tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        copied += 1
    for m in sorted(dest.iterdir()):
        if not m.is_file() or not m.name.isdigit() or m.name in here:
            continue
        mark = dest / f"{m.name}.gone"
        try:
            since = datetime.fromisoformat(mark.read_text().strip())
        except (OSError, ValueError):
            tmp = dest / f"{m.name}.gone.partial"
            tmp.write_text(now.isoformat())
            os.chmod(tmp, 0o600)
            os.replace(tmp, mark)
            continue
        if now - since >= timedelta(days=GONE_DAYS):
            m.unlink(missing_ok=True)
            mark.unlink(missing_ok=True)
    return copied


def backup_all(books, dest_dir: Path, keep: int = KEEP) -> tuple[list[Path], list[str]]:
    """The directory first, then each available book. A book that can't be opened is skipped and said."""
    _check(dest_dir, books.settings.key_path)
    stamp = _stamp()
    written = [backup_engine(books.directory, dest_dir, "steward-directory", stamp, keep)]
    skipped: list[str] = []
    for book in books.books():
        if book.id in books.unavailable:
            skipped.append(f"Skipped {book.slug}: {books.unavailable[book.id]}")
            continue
        written.append(backup_engine(books.engine_for(book), dest_dir, f"steward-{book.slug}", stamp, keep))
        files = books.files_dir(book)
        if files.is_dir():
            mirror = dest_dir / f"steward-{book.slug}-files"
            try:
                mirror_files(files, mirror)
            except OSError as e:
                skipped.append(f"Skipped the files copy for {book.slug}: {e.strerror or e}")
                continue
            written.append(mirror)
    return written, skipped
