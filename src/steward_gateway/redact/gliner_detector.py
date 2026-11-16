"""GLiNER-PII (spec 4.3): urchade/gliner_multi_pii-v1 on the GPU, CPU when there is none (the models eval in WSL).
Needs the models dependency group.

It reads only what nothing else finds in a typed question: people, street addresses and dates of birth (ruling of
2026-10-24, privacy approach review). Account, card, SSN, phone and email shapes are the question rule's, Presidio's
and the fingerprints' job, and the model's digit labels turned ages into "[ssn]"; organization left because in a
finance chat what the model calls an organization is the subject matter (Social Security, Roth IRA, fund tickers),
while every organization the book knows is caught by the NAS's exact pass and the fingerprints. Thresholds are per
label, chosen for recall on the models eval with the keep set as the brake: a lowercase street address scores about
0.28, so addresses read at 0.20."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from steward_boundary.spans import Edit, merge
from steward_gateway.redact import Span

GLINER_MODEL = "urchade/gliner_multi_pii-v1"
# The commits Steward downloads (threat model A5), so a changed upstream model can't arrive unseen. Looked up on the
# Hugging Face API on 2026-10-20 (docs/model-choice-2026-10.md). pytorch_model.bin is a pickle, and loading a pickle
# runs whatever it contains: the revision pin is what keeps an altered upload out.
GLINER_REVISION = "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d"         # lastModified 2024-04-20
# GLiNER builds its encoder and tokenizer from gliner_config.json's model_name, which it fetches by name with no
# revision. Steward fetches that repo itself at this commit and points model_name at the local snapshot.
GLINER_ENCODER = "microsoft/mdeberta-v3-base"
GLINER_ENCODER_REVISION = "a0484667b22365f84929a935b5e50a51f71f159d"  # lastModified 2023-04-06
# Only the encoder's config and tokenizer: GLiNER's own weights replace the encoder's.
ENCODER_FILES = ["*.json", "*.model", "*.txt"]

GLINER_LABELS = ["person", "street address", "date of birth"]
TOKENS = {"person": "[name]", "street address": "[address]", "date of birth": "[date of birth]"}
THRESHOLDS = {"person": 0.30, "street address": 0.20, "date of birth": 0.30}
# GLiNER cuts what it reads twice, silently: the words its data processor's splitter makes are cut at config.max_len
# (384 by default), then the label prompt plus those words are cut at the tokenizer's model_max_length subwords. The
# text is read in windows of GLiNER's own words, sized max_len less a margin, that overlap by OVERLAP words (Task 8.5):
# any entity of OVERLAP words or fewer lies whole inside at least one window. Each window's processed length is then
# measured exactly the way GLiNER will process it; a window over either limit is split in two overlapping halves, again
# and again, down to single characters (Task 8.6). Nothing is sent to the model that it would cut, and a chunk that
# can't fit even one character raises, which stops the turn: no text is ever sent unscanned. Spans found in two
# windows, or cut at a window's edge in one and whole in the next, merge into one.
DEFAULT_MAX_LEN = 384
OVERLAP = 64
_TOKEN_RE = re.compile(r"\w+(?:[-_]\w+)*|\S")      # GLiNER's WhitespaceTokenSplitter, for a model without one
_NO_LIMIT = 100_000                                  # transformers' "unset" model_max_length is a huge number


def _window_for(max_len: int) -> int:
    return max(2, max_len - max(16, max_len // 8))   # 336 words for GLiNER's default 384


WINDOW = _window_for(DEFAULT_MAX_LEN)


def tokens(text: str, split=None) -> list[tuple[int, int]]:
    """Character ranges of the words GLiNER will make of `text` (its own splitter when given)."""
    if split is not None:
        return [(int(a), int(b)) for _, a, b in split(text)]
    return [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def windows(text: str, window: int = WINDOW, overlap: int = OVERLAP, split=None) -> list[tuple[int, int]]:
    """Character ranges of the overlapping windows, covering every word of `text`."""
    toks = tokens(text, split)
    if not toks:
        return []
    overlap = min(overlap, window // 2)
    out, step = [], window - overlap
    for i in range(0, len(toks), step):
        j = min(len(toks), i + window)
        out.append((0 if i == 0 else toks[i][0], len(text) if j == len(toks) else toks[j - 1][1]))
        if j == len(toks):
            break
    return out


def _halves(n: int, overlap: int) -> tuple[int, int]:
    """Split n units (n >= 2) into [0, size) and [n - size, n), each about two thirds of n, sharing at least
    min(overlap, n // 3) units, so any run that short lies whole inside one half. The overlap is capped at a third so
    each split shrinks the halves geometrically (a fixed overlap near n would double the work at every level)."""
    ov = min(overlap, n // 3)
    size = (n + ov + 1) // 2
    return size, n - size


def load_pinned(GLiNER):
    """GLiNER-PII from the two pinned snapshots, with nothing fetched by name. Both repos are downloaded at their commit
    (a second start finds them in HF_HOME); GLiNER then loads a folder holding the model's files and a copy of its config
    whose model_name is the encoder snapshot's path, with local_files_only, so its own tokenizer and encoder-config
    lookups read that folder and never ask the hub.

    Gate finding PRIV-14: while the pinned mDeBERTa tokenizer loads, transformers 5.x logs that it has "an incorrect
    regex pattern" and advises fix_mistral_regex=True. That is expected and a false alarm. The check is for Mistral
    tokenizers and fires here only because the encoder's config.json has no transformers_version; with the flag unset
    the tokenizer is returned as loaded, which is how the models eval scored it. Don't "fix" it: the flag would swap
    mDeBERTa's pre-tokenizer for Mistral's and change what GLiNER reads (tests/gateway/test_gliner_pin.py fails if src
    ever passes or sets it; docs/guides/gateway.md tells the reader the line is expected)."""
    from huggingface_hub import snapshot_download
    model_dir = Path(snapshot_download(GLINER_MODEL, revision=GLINER_REVISION))
    config = json.loads((model_dir / "gliner_config.json").read_text())
    if config.get("model_name") != GLINER_ENCODER:
        raise RuntimeError(f"{GLINER_MODEL} at {GLINER_REVISION} is built on {config.get('model_name')!r}, "
                           "not GLINER_ENCODER; pin that encoder's commit first.")
    config["model_name"] = snapshot_download(GLINER_ENCODER, revision=GLINER_ENCODER_REVISION,
                                             allow_patterns=ENCODER_FILES)
    with tempfile.TemporaryDirectory(prefix="steward-gliner-") as folder:
        for f in model_dir.iterdir():
            if f.name != "gliner_config.json" and f.is_file():
                os.symlink(f.resolve(), Path(folder) / f.name)
        (Path(folder) / "gliner_config.json").write_text(json.dumps(config))
        return GLiNER.from_pretrained(folder, local_files_only=True)


class GlinerDetector:
    name = "gliner"

    def __init__(self, thresholds: dict[str, float] | None = None, *, model=None):
        self.thresholds = dict(THRESHOLDS if thresholds is None else thresholds)
        self.threshold = min(self.thresholds.values())      # what the model is asked for; each label then has its own
        real = model is None
        if real:
            for name, rev in (("GLINER_REVISION", GLINER_REVISION), ("GLINER_ENCODER_REVISION", GLINER_ENCODER_REVISION)):
                if not re.fullmatch(r"[0-9a-f]{40}", rev):
                    raise RuntimeError(f"{name} in gliner_detector.py must be a 40-character commit hash "
                                       "before the GLiNER-PII model can be downloaded.")
            import torch
            from gliner import GLiNER
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            model = load_pinned(GLiNER).to(self.device)
            model.eval()
        self.model = model              # tests pass a stand-in with GLiNER's predict_entities
        self.max_len = int(getattr(getattr(model, "config", None), "max_len", None) or DEFAULT_MAX_LEN)
        self.window = _window_for(self.max_len)
        self.overlap = min(OVERLAP, self.window // 2)
        dp = getattr(model, "data_processor", None)
        splitter = getattr(dp, "words_splitter", None)
        self._split = splitter if callable(splitter) else None
        tok = getattr(dp, "transformer_tokenizer", None)
        limit = getattr(tok, "model_max_length", None)
        self._subwords = (tok, dp.prepare_inputs) if tok is not None and hasattr(dp, "prepare_inputs") else None
        if not (isinstance(limit, int) and 0 < limit < _NO_LIMIT):
            # mdeberta-v3-base's tokenizer leaves model_max_length unset; the encoder's own position limit (512) is
            # what bounds its input (found on deploy day, 2026-10-24).
            enc = getattr(getattr(model, "config", None), "encoder_config", None)
            limit = getattr(enc, "max_position_embeddings", None)
        self.subword_limit = int(limit) if isinstance(limit, int) and 0 < limit < _NO_LIMIT else None
        if real and (self._split is None or self._subwords is None or not callable(self._subwords[1])
                     or self.subword_limit is None):
            # Without GLiNER's own splitter, prepare_inputs and the tokenizer's limit, _fits can't measure what the
            # model would cut, and a subword tail could go unscanned. Refuse to start: chat stays off, with the
            # reason in health (final review, finding 2).
            raise RuntimeError("This GLiNER build doesn't expose the limits Steward needs to read every word.")

    def _fits(self, chunk: str, toks: list[tuple[int, int]]) -> bool:
        """True when GLiNER will read every word of `chunk`: no more than max_len words, and the label prompt plus the
        words within the tokenizer's limit, measured the way GLiNER's processor builds its input."""
        if len(toks) > self.max_len:
            return False
        if self._subwords is None or self.subword_limit is None:
            return True
        tok, prepare = self._subwords
        input_texts, _ = prepare([[chunk[a:b] for a, b in toks]], GLINER_LABELS)
        ids = tok(input_texts, is_split_into_words=True, truncation=False)["input_ids"][0]
        return len(ids) <= self.subword_limit

    def _scan(self, text: str, start: int, end: int, found: dict[str, list[Edit]]) -> None:
        stack = [(start, end)]
        while stack:
            a, b = stack.pop()
            chunk = text[a:b]
            toks = tokens(chunk, self._split)
            if not toks:
                continue
            if self._fits(chunk, toks):
                for e in self.model.predict_entities(chunk, GLINER_LABELS, threshold=self.threshold):
                    if e.get("score", 1.0) < self.thresholds[e["label"]]:
                        continue
                    label = TOKENS[e["label"]]
                    found.setdefault(label, []).append(Edit(a + int(e["start"]), a + int(e["end"]), label, "gliner"))
                continue
            if len(toks) >= 2:          # split by words
                size, second = _halves(len(toks), self.overlap)
                stack += [(a + toks[second][0], a + toks[-1][1]), (a + toks[0][0], a + toks[size - 1][1])]
                continue
            s, e = toks[0]              # one word GLiNER can't read whole (a long unspaced CJK run): split by letters
            if e - s < 2:
                raise RuntimeError("GLiNER can't read even one character of this text within its limits.")
            size, second = _halves(e - s, self.overlap)
            stack += [(a + s + second, a + e), (a + s, a + s + size)]

    def detect(self, text: str) -> list[Span]:
        found: dict[str, list[Edit]] = {}
        for start, end in windows(text, self.window, self.overlap, self._split):
            self._scan(text, start, end, found)
        # Merged label by label: a person inside a wider address span keeps its own "[name]" span, which the
        # second pass (checks.py) stops on; redact() merges across labels when it replaces.
        return [Span(e.start, e.end, e.label, "gliner") for edits in found.values() for e in merge(edits)]
