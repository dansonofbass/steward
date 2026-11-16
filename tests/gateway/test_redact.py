import re

import pytest

from steward_gateway.redact import Guarded, Span, detect_all, redact
from steward_gateway.redact.patterns import PatternDetector, aba, luhn
from tests.gateway.fakes import THIRD_PARTY_NAMES, NameListDetector

DET = [PatternDetector(), NameListDetector()]


@pytest.mark.parametrize("text, label", [
    ("write to dortiz@example.com today", "[email]"),
    ("call (714) 555-0102", "[phone]"),
    ("call 714.555.0148 please", "[phone]"),
    ("my SSN is 900-12-3456", "[ssn]"),
    ("card 4111 1111 1111 1111 expired", "[card number]"),
    ("routing 021000021 for the wire", "[routing number]"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "[iban]"),
    ("she was born 03/14/1950", "[date of birth]"),
    ("DOB: March 14, 1950", "[date of birth]"),
    ("her birthday is Mar. 14 1941", "[date of birth]"),
    ("account 4417002918 at the bank", "[account number]"),
])
def test_pattern_identifiers_are_found(text, label):
    assert label in {s.label for s in detect_all(text, DET)}


def test_checksums():
    assert luhn("4111111111111111") and not luhn("4111111111111112")
    assert aba("021000021") and not aba("021000022")


def test_a_card_that_fails_luhn_is_still_an_account_number():
    assert {s.label for s in detect_all("number 4111 1111 1111 1112", DET)} == {"[account number]"}


def test_names_become_brackets_and_aliases_stay():
    issued = {"Person 1", "Account 3"}
    r = redact("Did Person 1 pay Tom Becker, or did Dr. Alvarez's office bill Account 3?", DET, issued)
    assert r.text == "Did Person 1 pay [name], or did [name]'s office bill Account 3?"
    assert [e.layer for e in r.edits] == ["gliner", "gliner"]


def test_the_keep_list_survives():
    for text in ("Are we spending more than $12,345.67 on dining in 2026?", "When can we claim Social Security at 67?",
                 "Is VTI or BND a bigger share of the IRA?", "We moved to CA in 2019", "Medicare Part D at $38.40"):
        assert redact(text, DET).text == text


def test_every_third_party_name_is_covered():
    for name in THIRD_PARTY_NAMES:
        assert redact(f"Did we pay {name} last month?", DET).text != f"Did we pay {name} last month?"
    assert redact("Did we pay Jonah Wexler?", DET).text == "Did we pay [name]?"


def test_keep_words_are_never_replaced():
    class OrgEverything:
        name = "gliner"

        def detect(self, text):
            i = text.find("Social Security")
            return [Span(i, i + len("Social Security"), "[organization]", "gliner")] if i >= 0 else []
    assert redact("Social Security arrives on the 3rd", [OrgEverything()]).text == "Social Security arrives on the 3rd"


def test_overlapping_spans_take_the_wider():
    r = redact("email tom@example.com", DET + [NameListDetector(("tom",))])
    assert r.text == "email [email]"


def test_look_alike_letters_dont_hide_a_name():
    r = redact("Did T" + chr(0x43E) + "m Becker call?", DET)
    assert r.text == "Did [name] call?"


def test_guarded_detectors_behave_the_same():
    assert redact("call 714-555-0102", [Guarded(DET)]).text == "call [phone]"


# Task 2.5 API: only aliases the NAS issued this turn are protected; edits are made on the plain text.
class _Whole:
    """A detector that tags the entire text as a name, like a model that read an alias and a surname as one person."""
    name = "gliner"

    def detect(self, text):
        return [Span(0, len(text), "[name]", "gliner")]


def test_an_issued_alias_is_cut_out_of_a_wider_span():
    r = redact("Person 1 Margaret", [_Whole()], {"Person 1"})
    assert r.text == "Person 1[name]"
    assert [(e.start, e.end) for e in r.edits] == [(8, 17)]


def test_a_typed_look_alike_alias_shields_nothing():
    assert redact("Person 1 Margaret", [_Whole()]).text == "[name]"
    assert redact("Person 1 Margaret", [_Whole()], {"Person 2"}).text == "[name]"
    assert redact("[name]Margaret", [_Whole()]).text == "[name]"   # a typed bracket is text, not an issued token


def test_an_issued_bracket_is_protected_as_written():
    assert redact("[payee] Margaret", [_Whole()], {"[payee]"}).text == "[payee][name]"


def test_a_token_that_is_not_issuable_is_refused():
    with pytest.raises(ValueError):
        redact("hello", DET, {"Margaret"})


def test_edits_refer_to_the_plain_text_when_invisible_characters_are_dropped():
    r = redact("Did Tom​ Becker call?", DET)
    assert r.text == "Did [name] call?"
    r = redact("Ｔom Becker said hi", DET)   # a full-width T is a plain T after NFKC
    assert r.text == "[name] said hi"


def test_a_date_of_birth_in_any_form_is_found():
    for text in ("born 1941", "DOB 03-14-1950", "born on 14 March 1950"):
        assert "[date of birth]" in {s.label for s in detect_all(text, DET)}, text


# --- Task 8.5: detection on the canonical view, GLiNER windows, overlapping detector spans --------------------------
def test_a_name_in_look_alike_letters_is_found():
    # Greek capital tau and beta, Cyrillic o and e.
    r = redact("Did Τоm Βеcker call?", DET)
    assert r.text == "Did [name] call?"


def test_accents_line_breaks_and_hidden_breaks_dont_split_a_name():
    assert redact("Did Tóm Becker call?", DET).text == "Did [name] call?"
    assert redact("Did Tom\n\n  Becker call?", DET).text == "Did [name] call?"     # not "[name]\n\n  Becker"
    assert redact("Did Tom​Becker call?", DET).text == "Did [name] call?"      # a zero-width space, no space
    assert redact("Did TomBecker call?", DET).text == "Did [name] call?"


def test_case_changes_that_change_length_dont_move_the_edits():
    # "ß" casefolds to "ss" and "İ" to "i" plus a dot: the canonical view is longer or shorter than the plain text.
    assert redact("Straße trip with Tom Becker", DET).text == "Straße trip with [name]"
    assert (redact("İİİ and ẞẞ paid Tom Becker 714-555-0102", DET).text
            == "İİİ and ẞẞ paid [name] [phone]")


def test_full_width_and_other_digits_are_found():
    assert redact("card ４１１１ １１１１ １１１１ "
                  "１１１１", DET).text == "card [card number]"
    assert redact("SSN 900-12-３４５６", DET).text == "SSN [ssn]"
    arabic = "".join(chr(0x660 + int(d)) for d in "4111111111111111")
    assert redact(f"card {arabic}", DET).text == "card [card number]"


def test_overlapping_spans_from_one_detector_merge_and_leave_no_digits():
    # The SSN and phone shapes match the first digits and the long run matches them all; the wider one covers the rest.
    assert redact("acct 900-12-3456-7890-12", DET).text == "acct [account number]"
    assert redact("phone 714-555-0102-3399-01", DET).text == "phone [account number]"


def test_partly_overlapping_spans_from_two_detectors_merge_whatever_the_order():
    class Tags:
        name = "gliner"

        def __init__(self, word):
            self.word = word

        def detect(self, text):
            i = text.find(self.word)
            return [Span(i, i + len(self.word), "[name]", "gliner")] if i >= 0 else []
    a, b = Tags("Tom Be"), Tags("Becker")
    assert redact("Did Tom Becker call?", [a, b]).text == "Did [name] call?"
    assert redact("Did Tom Becker call?", [b, a]).text == "Did [name] call?"


def test_detect_all_cuts_a_span_on_both_sides_of_an_issued_alias():
    spans = detect_all("Tom Person 1 Becker", [_Whole()], {"Person 1"})
    assert [(s.start, s.end) for s in spans] == [(0, 4), (12, 19)]
    assert redact("Tom Person 1 Becker", [_Whole()], {"Person 1"}).text == "[name]Person 1[name]"


class _FakeGliner:
    """Finds "Tom Becker", or just "Tom" when the window ends there, only inside the text it is given, like GLiNER
    reading one window."""

    def __init__(self):
        self.chunks = []

    def predict_entities(self, chunk, labels, threshold):
        import re
        self.chunks.append(chunk)
        return [{"start": m.start(), "end": m.end(), "label": "person"}
                for m in re.finditer(r"Tom(?: Becker)?(?![\w])", chunk)]


def test_gliner_finds_a_name_across_a_window_edge():
    from steward_gateway.redact import gliner_detector as G
    model = _FakeGliner()
    det = G.GlinerDetector(model=model)
    for before in range(G.WINDOW - 3, G.WINDOW + 2):      # the name straddles the first window's edge
        text = "word " * before + "Tom Becker" + " word" * 300
        start = text.index("Tom Becker")
        assert [(s.start, s.end, s.label) for s in det.detect(text)] == [(start, start + 10, "[name]")], before
    assert len(model.chunks) > 2


def test_gliner_keeps_a_name_inside_a_wider_address_span():
    from steward_gateway.redact import gliner_detector as G

    class Both:
        def predict_entities(self, chunk, labels, threshold):
            i = chunk.find("Tom Becker")
            return [{"start": 0, "end": len(chunk), "label": "street address"},
                    {"start": i, "end": i + 10, "label": "person"}] if i >= 0 else []
    spans = G.GlinerDetector(model=Both()).detect("Tom Becker and Sons")
    assert sorted((s.start, s.end, s.label) for s in spans) == [(0, 10, "[name]"), (0, 19, "[address]")]


def test_gliner_windows_overlap_by_at_least_the_longest_entity():
    from steward_gateway.redact import gliner_detector as G
    assert G.OVERLAP >= 64 and G.WINDOW > G.OVERLAP
    text = " ".join(f"w{i}" for i in range(1000))
    wins = G.windows(text)
    assert wins[0][0] == 0 and wins[-1][1] == len(text)
    toks = G.tokens(text)
    for k in range(len(toks) - G.OVERLAP + 1):          # every run of OVERLAP tokens lies inside one window
        a, b = toks[k][0], toks[k + G.OVERLAP - 1][1]
        assert any(s <= a and b <= e for s, e in wins), k
    assert G.windows("") == [] and G.windows("short text") == [(0, 10)]



class _GlinerReader:
    """Reads a chunk the way GLiNER 0.2.29 does (Task 8.6): its data processor's word splitter, the words cut at
    config.max_len, then the label prompt plus the words cut at the tokenizer's model_max_length subwords. It finds
    names only in the words that survive both cuts and records what it never read."""

    class _Tokenizer:
        def __init__(self, limit):
            self.model_max_length = limit

        @staticmethod
        def pieces(word):
            import re
            return len(re.findall(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]", word)) or 1   # each CJK letter or mark is a piece

        def __call__(self, input_texts, is_split_into_words=True, truncation=False, **kw):
            assert is_split_into_words and not truncation
            return {"input_ids": [[0] * (2 + sum(self.pieces(w) for w in words)) for words in input_texts]}

    class _Processor:
        def __init__(self, splitter, limit):
            self.words_splitter = splitter
            self.transformer_tokenizer = _GlinerReader._Tokenizer(limit)

        def prepare_inputs(self, texts, entities, **kw):
            prompt = [t for e in entities for t in ("<<ENT>>", e)] + ["<<SEP>>"]
            return [prompt + list(t) for t in texts], [len(prompt)] * len(texts)

    def __init__(self, names=("Tom Becker",), max_len=384, limit=512, splitter=None):
        import re
        from types import SimpleNamespace
        ws = re.compile(r"\w+(?:[-_]\w+)*|\S")
        splitter = splitter or (lambda text: ((m.group(), m.start(), m.end()) for m in ws.finditer(text)))
        self.config = SimpleNamespace(max_len=max_len)
        self.data_processor = self._Processor(splitter, limit)
        self.names = re.compile("|".join(re.escape(n) for n in names))
        self.truncated, self.chunks = 0, []

    def predict_entities(self, chunk, labels, threshold):
        self.chunks.append(chunk)
        words = list(self.data_processor.words_splitter(chunk))
        kept = words[:self.config.max_len]
        tok = self.data_processor.transformer_tokenizer
        prompt, _ = self.data_processor.prepare_inputs([[]], labels)
        budget = tok.model_max_length - 2 - sum(tok.pieces(w) for w in prompt[0])
        read = 0
        for w in kept:
            budget -= tok.pieces(w[0])
            if budget < 0:
                break
            read += 1
        if read < len(words):
            self.truncated += 1
        seen_end = words[read - 1][2] if read else 0
        return [{"start": m.start(), "end": m.end(), "label": "person"}
                for m in self.names.finditer(chunk) if m.end() <= seen_end]


def _only_names(det, text, names=("Tom Becker",)):
    want = sorted((i, i + len(n)) for n in names for i in [text.index(n)])
    assert sorted((s.start, s.end) for s in det.detect(text) if s.label == "[name]") == want


def test_gliner_windows_use_the_models_own_max_len_with_a_margin():
    from steward_gateway.redact import gliner_detector as G
    assert G.DEFAULT_MAX_LEN == 384 and G.WINDOW < G.DEFAULT_MAX_LEN and G.WINDOW > G.OVERLAP
    det = G.GlinerDetector(model=_GlinerReader(max_len=200, limit=10**6))
    assert det.max_len == 200 and det.window < 200
    text = " ".join(f"w{i}" for i in range(1000))
    det.detect(text)
    assert det.model.truncated == 0 and len(det.model.chunks) > 5


def test_gliner_windows_use_the_models_word_splitter():
    """A splitter that cuts at hyphens (spaCy-like) makes three words of "a-b" where our own regex makes one: windows
    sized by our regex would pass max_len and GLiNER would cut the tail, where the name sits."""
    import re

    from steward_gateway.redact import gliner_detector as G
    fine = re.compile(r"[A-Za-z0-9]+|\S")
    model = _GlinerReader(max_len=200, limit=10**6,
                          splitter=lambda t: ((m.group(), m.start(), m.end()) for m in fine.finditer(t)))
    old_cut = 200 // 3                                    # where GLiNER would have cut a 256-token regex window
    text = "a-b " * (old_cut + 2) + "Tom Becker" + " a-b" * 400
    _only_names(G.GlinerDetector(model=model), text)
    assert model.truncated == 0


def test_gliner_punctuation_dense_text_is_split_until_it_fits():
    """"x-x-x-x-x" is one word to GLiNER's whitespace splitter but nine subwords: a window of 256 such words is far
    past 512 subwords, and the old window cut everything after about 50 of them."""
    from steward_gateway.redact import gliner_detector as G
    model = _GlinerReader()
    text = "x-x-x-x-x " * 60 + "Tom Becker" + " x-x-x-x-x" * 600
    _only_names(G.GlinerDetector(model=model), text)
    assert model.truncated == 0


def test_gliner_cjk_heavy_text_is_split_until_it_fits():
    from steward_gateway.redact import gliner_detector as G
    model = _GlinerReader(names=("Tom Becker", "山田太郎"))
    text = "東京の銀行口座について " * 50 + "山田太郎 さん と Tom Becker" + " 東京の銀行口座について" * 300
    _only_names(G.GlinerDetector(model=model), text, ("Tom Becker", "山田太郎"))
    assert model.truncated == 0


def test_gliner_one_word_past_the_subword_limit_is_split_by_characters():
    from steward_gateway.redact import gliner_detector as G
    model = _GlinerReader()
    text = "".join(chr(0x4E00 + i) for i in range(3000)) + " Tom Becker " + "".join(chr(0x6000 + i) for i in range(3000))
    _only_names(G.GlinerDetector(model=model), text)
    assert model.truncated == 0
    covered = set()
    for c in model.chunks:                                # every character went to the model in some chunk (the
        i = text.find(c)                                  # letters are all different, so find() is exact)
        covered.update(range(i, i + len(c)))
    assert covered >= {i for i, ch in enumerate(text) if not ch.isspace()}


def test_gliner_name_just_past_the_old_cut_is_found():
    """The old 256-token window of three-subword words passes 512 subwords near word 160: a name placed right after,
    and before the next window began (token 192), was never read."""
    from steward_gateway.redact import gliner_detector as G
    model = _GlinerReader()
    for before in range(150, 175, 4):
        model.truncated = 0
        text = "a-b " * before + "Tom Becker" + " a-b" * 500
        _only_names(G.GlinerDetector(model=model), text)
        assert model.truncated == 0, before


def test_gliner_fails_closed_when_nothing_fits():
    from steward_gateway.redact import gliner_detector as G
    det = G.GlinerDetector(model=_GlinerReader(limit=5))   # the label prompt alone is past the limit
    with pytest.raises(RuntimeError):
        det.detect("Tom Becker called")

@pytest.mark.parametrize("digits", [18, 20, 24, 30])
@pytest.mark.parametrize("sep", ["", " ", "-"])
def test_long_digit_runs_are_masked_whole(digits, sep):
    run = sep.join("1234567890"[i % 10] for i in range(digits))
    for detectors in ([PatternDetector()],):
        assert redact(f"acct {run} end", detectors).text == "acct [account number] end"


def test_the_presidio_account_pattern_has_no_upper_bound():
    import re

    from steward_gateway.redact.patterns import LONG
    assert re.fullmatch(LONG.pattern, "1" * 24) and re.fullmatch(LONG.pattern, "1234 5678 9012 3456 7890 1234")


# --- A real model without the parts _fits needs refuses to start (final review, finding 2) -----------------------------
def _fake_real_gliner(monkeypatch, model):
    """Stand in for the gliner and torch packages and the pinned download, so GlinerDetector() takes its real-model path
    with `model` and never reaches the hub."""
    import sys
    from types import ModuleType, SimpleNamespace

    class _Loaded:
        def to(self, device):
            return self

        def eval(self):
            return None
    loaded = model

    def from_pretrained(name, **kwargs):
        wrapper = _Loaded()
        wrapper.__dict__.update(loaded.__dict__)
        wrapper.predict_entities = loaded.predict_entities
        return wrapper
    gliner = ModuleType("gliner")
    gliner.GLiNER = SimpleNamespace(from_pretrained=from_pretrained)
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: False)
    monkeypatch.setitem(sys.modules, "gliner", gliner)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr("steward_gateway.redact.gliner_detector.load_pinned", lambda G: G.from_pretrained("pinned"))


@pytest.mark.parametrize("missing", ["words_splitter", "prepare_inputs", "model_max_length"])
def test_a_real_gliner_without_its_limits_refuses_to_start(monkeypatch, missing):
    from steward_gateway.redact import gliner_detector as G
    model = _GlinerReader()
    dp = model.data_processor
    if missing == "words_splitter":
        dp.words_splitter = None
    elif missing == "prepare_inputs":
        dp.prepare_inputs = None
    else:
        dp.transformer_tokenizer.model_max_length = int(1e30)    # transformers' "unset"
    _fake_real_gliner(monkeypatch, model)
    with pytest.raises(RuntimeError):
        G.GlinerDetector()


def test_a_tokenizer_with_no_limit_falls_back_to_the_encoders_position_limit(monkeypatch):
    """The real urchade/gliner_multi_pii-v1 tokenizer (mdeberta-v3-base) leaves model_max_length unset; the encoder's
    own config says 512 positions (found on deploy day, 2026-10-24). That is the limit, not a reason to refuse."""
    from types import SimpleNamespace

    from steward_gateway.redact import gliner_detector as G
    model = _GlinerReader()
    model.data_processor.transformer_tokenizer.model_max_length = int(1e30)    # transformers' "unset"
    model.config.encoder_config = SimpleNamespace(max_position_embeddings=512)
    _fake_real_gliner(monkeypatch, model)
    det = G.GlinerDetector()
    assert det.subword_limit == 512


def test_a_real_gliner_with_its_limits_starts(monkeypatch):
    from steward_gateway.redact import gliner_detector as G
    _fake_real_gliner(monkeypatch, _GlinerReader())
    det = G.GlinerDetector()
    assert det.subword_limit == 512 and det._split is not None and det._subwords is not None


def test_a_gliner_without_its_limits_leaves_chat_off_with_the_reason(monkeypatch):
    from steward_gateway.redact import load_real_detectors
    model = _GlinerReader()
    model.data_processor.words_splitter = None
    _fake_real_gliner(monkeypatch, model)
    found, problem = load_real_detectors()
    assert found == [] and problem == "The redaction models didn't load (RuntimeError)."


def test_health_names_the_reason_when_gliner_lacks_its_limits(gw_cfg, monkeypatch):
    from fastapi.testclient import TestClient

    from steward_gateway.app import create_gateway_app
    from steward_gateway.secrets import write_private
    model = _GlinerReader()
    model.data_processor.prepare_inputs = None
    _fake_real_gliner(monkeypatch, model)
    write_private(gw_cfg.token_path, "c" * 64)
    with TestClient(create_gateway_app(gw_cfg, client=None)) as c:
        body = c.get("/v1/health", headers={"Authorization": "Bearer " + "c" * 64}).json()
    assert body["redaction_ready"] is False
    assert body["redaction_problem"] == "The redaction models didn't load (RuntimeError)."



# --- The model's job, cut to what nothing else finds (privacy approach review, 2026-10-24) ---------------------------
def test_gliner_reads_only_people_street_addresses_and_dates_of_birth():
    """Account, card, SSN, phone and email shapes are the question rule's, Presidio's and the fingerprints' job (the
    ssn label turned "62" into [ssn]); organization left the model by ruling (it fired on the finance vocabulary)."""
    from steward_gateway.redact import gliner_detector as G
    assert G.GLINER_LABELS == ["person", "street address", "date of birth"]
    assert set(G.TOKENS) == set(G.GLINER_LABELS) == set(G.THRESHOLDS)
    assert {G.TOKENS[k] for k in G.GLINER_LABELS} == {"[name]", "[address]", "[date of birth]"}


def test_gliner_applies_each_labels_threshold():
    from steward_gateway.redact import gliner_detector as G

    class Scored:
        def predict_entities(self, chunk, labels, threshold):
            assert threshold == min(G.THRESHOLDS.values())
            return [{"start": 0, "end": 3, "label": "person", "score": G.THRESHOLDS["person"]},
                    {"start": 4, "end": 8, "label": "date of birth", "score": G.THRESHOLDS["date of birth"] - 0.01}]
    assert [(s.start, s.end, s.label) for s in G.GlinerDetector(model=Scored()).detect("Tom 3/14")] == [
        (0, 3, "[name]")]


class _Tags:
    """A model layer that tags each given stretch of the text with a label, the way GLiNER guesses."""
    name = "gliner"

    def __init__(self, *tags):
        self.tags = tags

    layer = "gliner"

    def detect(self, text):
        out = []
        for piece, label in self.tags:
            # the piece as a whole word, so "I" is the pronoun and not the I of "If" (final review F5)
            m = re.search(rf"(?<!\w){re.escape(piece)}(?!\w)", text)
            if m:
                out.append(Span(m.start(), m.end(), label, self.layer))
        return out


class _PresidioTags(_Tags):
    name = "presidio"
    layer = "presidio"


@pytest.mark.parametrize("text, piece, label", [
    ("When can we claim Social Security if we stop working at 62?", "62", "[date of birth]"),
    ("Did dining go up 6.5% since 2031?", "2031", "[date of birth]"),
    ("Our kids are 3, 10 and 16; what will college cost?", "3, 10 and 16", "[name]"),
    ("Our kids are 3, 10 and 16; what will college cost?", "Our kids", "[name]"),
    ("How much is in the Roth IRA and the HSA, and is VXUS the bigger share?", "the Roth IRA and the HSA", "[name]"),
    ("When can we claim Social Security if we stop working at 70?", "Social Security if", "[name]"),
    ("If I put $185 more a month into the 401(k), can we retire at 67?", "I", "[name]"),
    ("We live in Texas; does that change the tax on $12k?", "We", "[name]"),
    ("We live in New York; does that change the tax on $12k?", "New York", "[address]"),
])
def test_model_spans_that_name_nobody_are_dropped(text, piece, label):
    assert redact(text, [_Tags((piece, label))]).text == text


@pytest.mark.parametrize("text, piece, label, want", [
    ("Did Tom Becker get paid?", "Tom Becker", "[name]", "Did [name] get paid?"),
    ("my brother tom becker paid me back", "my brother tom becker", "[name]", "[name] paid me back"),
    # No ticker-shape rule: a name typed in capitals stays a name. The real model doesn't read the keep set's tickers
    # as people, holding symbols are proven by schema, and a ticker guess costs a chip, never a stop.
    ("Is JONAH on the plan?", "JONAH", "[name]", "Is [name] on the plan?"),
    ("Mail it to Juniper Court, Brea", "Juniper Court, Brea", "[address]", "Mail it to [address]"),
    ("Mom's birthday is March 14", "March 14", "[date of birth]", "Mom's birthday is [date of birth]"),
    ("She was 12345 years old", "12345", "[name]", "She was [name] years old"),
    # A person's name made of words that are also states, months or state codes is still a name (final review F3).
    ("Did Georgia Washington pay?", "Georgia Washington", "[name]", "Did [name] pay?"),
    ("Did Al May pay?", "Al May", "[name]", "Did [name] pay?"),
    ("Is Ms Georgia on the plan?", "Ms Georgia", "[name]", "Is [name] on the plan?"),
    ("Did June Carolina call?", "June Carolina", "[name]", "Did [name] call?"),
    ("Did Mo Dakota call?", "Mo Dakota", "[name]", "Did [name] call?"),
    ("Is Virginia B on the plan?", "Virginia B", "[name]", "Is [name] on the plan?"),
])
def test_model_spans_that_could_name_someone_stay(text, piece, label, want):
    assert redact(text, [_Tags((piece, label))]).text == want


def test_only_model_spans_are_judged_by_whether_they_name_anybody():
    """names_nobody is for GLiNER's guesses; a Presidio email whose every word is a generic word is still an email
    (final review F8)."""
    from steward_gateway.redact import names_nobody
    assert names_nobody("home@bank.co", "[email]")
    assert redact("write to home@bank.co today", [_PresidioTags(("home@bank.co", "[email]"))]).text == \
        "write to [email] today"
    assert redact("write to home@bank.co today", [_Tags(("home@bank.co", "[email]"))]).text == \
        "write to home@bank.co today"


def test_a_model_span_on_an_alias_or_bracket_that_wasnt_issued_still_counts():
    """Generic words include the alias words, but a typed "Person 7" or "[payee]" the NAS didn't issue is checked
    like any other text (Task 2.5): the span-boundary filter must not undo that."""
    assert redact("Did Person 1 pay Person 7?", [_Tags(("Person 7", "[name]"))], {"Person 1"}).text == \
        "Did Person 1 pay [name]?"
    assert redact("Did [payee] call?", [_Tags(("[payee]", "[name]"))]).text == "Did [name] call?"
    assert redact("Did Person 1 call?", [_Tags(("Person 1", "[name]"))], {"Person 1"}).text == "Did Person 1 call?"


def test_what_is_left_of_a_span_around_an_issued_token_is_judged_on_its_own():
    """The second pass reads the redacted question: a model span "my brother [name]" around the gateway's own issued
    "[name]" leaves "my brother ", which names nobody, so the turn isn't stopped (found on the real model,
    2026-10-24: 29 of 400 PII questions stopped after a clean redaction)."""
    text = "my brother [name] paid me back $200, did it arrive?"
    assert detect_all(text, [_Tags(("my brother [name]", "[name]"))], {"[name]"}) == []
    assert detect_all("We moved to • [address] last spring", [_Tags(("• [address]", "[address]"))], {"[address]"}) == []
    assert [(s.start, s.end) for s in detect_all("Tom [name] paid", [_Tags(("Tom [name]", "[name]"))], {"[name]"})] == [
        (0, 4)]


@pytest.mark.parametrize("text", ["my password is New York", "the password is New Jersey", "my password is Roth",
                                  "my password is Medicare", "my password is groceries"])
def test_a_password_that_is_a_keep_word_still_goes(text):
    """A keep word is put back when a model names it, but not when it is a password's value (second adversarial
    round, 2026-10-25)."""
    out = redact(text, [PatternDetector()]).text
    assert out.endswith("is [secret]"), out
