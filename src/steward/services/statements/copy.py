"""The words the server says about statements (PDF statements spec, Copy: Statement errors; plan-owned where marked).
A stage's error column holds the key, never free text."""
ERRORS = {
    "too_big": "Bigger than 15 MB. Download it again or split it.",
    "too_many_pages": "More than 60 pages. Split it and try again.",
    "password": "This PDF has a password. Save a copy without one and try again.",
    "not_pdf": "This isn't a PDF.",
    "unreadable": "This PDF couldn't be read.",
    "too_slow": "This PDF took too long to read.",
    "not_statement": "This doesn't look like a statement.",
    "no_period": "The statement period couldn't be found. Check rows",
    "too_many_rows": "More than 2,000 rows. Split it and try again.",                         # plan-owned
    "too_many_holdings": "More than 200 holdings. Split it and try again.",                   # plan-owned
    "scanned_later": "Steward can't read scanned pages yet.",                                 # plan-owned, until PR 2
    "kind_later": "Steward can't read this kind of statement yet.",                           # plan-owned, until PR 3
    "layout_failed": "{gateway} couldn't read this layout · Try again",                       # plan-owned, until PR 2
    "page_failed": "{gateway} couldn't read page {n} · Try again",
    "read_failed": "{gateway} couldn't read this file · Try again",                  # remote-reading P66
    "restarted": "Steward restarted on page {n} of {m}. Add the file again to finish.",
    "gone":"Steward restarted before reading this. Add the file again.",                     # plan-owned
}
BUSY = "Steward is busy with other files. Try again in a few minutes."
HELD = "Steward is holding files until {gateway} is back. Try again then."   # remote-reading P65
TOO_MANY = "A batch holds up to 30 files. Import these, then add the rest."
SAME_FILE = "This file is already in the batch."
NOT_A_PDF_TYPE = "That request wasn't understood."
NOT_PAIRED = "Reading this needs {gateway}. Pair it in Settings › Chat."
CLEARED_LOG = "{n} statements waiting to import were cleared after a week."
CLEARED_LOG_ONE = "1 statement waiting to import was cleared after a week."                  # plan-owned singular
WARN_EVENT = "{n} statements waiting to import go on {day}."
WARN_EVENT_ONE = "1 statement waiting to import goes on {day}."                              # plan-owned singular
NO_STATEMENT = "That statement isn't here anymore."                                          # plan-owned
NOT_NOW = "That statement can't be changed right now."                                       # plan-owned
