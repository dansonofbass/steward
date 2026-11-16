"""The boundary's mask_numbers is the same rule as present.py's (spec 4.5): checked on fixed examples and on 2,000
seeded random strings with no keep-list stretches in them."""
import random

from steward.inventory.present import mask_numbers as present_mask
from steward_boundary.text import mask_numbers, outgoing_text

FIXED = ["1234 5678 9012", "4417", "Checking 123456789", "x4417", "CHECK 1043 ON 10/16", "ZELLE TO J. 4029357733",
         "Way2Save savings", "", "••6789 and 12345", "a1b2c3d4e5"]


def test_fixed_examples_match():
    for s in FIXED:
        assert mask_numbers(s) == present_mask(s), s


def test_random_strings_match():
    rng = random.Random(20261020)
    alphabet = "0123456789" + "abcdefgh" + "  -./#$,%•"
    for _ in range(2000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        assert mask_numbers(s) == present_mask(s), s


def test_outgoing_text_agrees_when_nothing_is_on_the_keep_list():
    """Digits always touch a letter here (no small standalone numbers), there are no 1, 2, 9 or 0 (no years), no
    capitals (no aliases) and no $ , % (no money or percentages), so outgoing_text must be exactly mask_numbers."""
    rng = random.Random(20261021)
    for _ in range(2000):
        words = ["".join([rng.choice("abcdefgh"), *(rng.choice("345678") for _ in range(rng.randint(0, 4))),
                          rng.choice("abcdefgh")]) for _ in range(rng.randint(0, 6))]
        s = "".join(w + rng.choice(["", " ", "-", ".", "/", "  "]) for w in words)
        assert outgoing_text(s) == present_mask(s), s
