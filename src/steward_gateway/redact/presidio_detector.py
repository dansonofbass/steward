"""Presidio's analyzer recognizers, pattern-based only, with no spaCy model loaded (spec 4.3): email, phone, US SSN,
card numbers with Luhn, ABA routing with its checksum, IBAN, plus three of our own patterns: any SSN shape (Presidio
rejects some ranges the fictional set uses), dates of birth next to "born"/"DOB"/"birthday", and long digit runs;
and the boundary's PIN, password or code rule (patterns.secrets), which no regular expression alone can carry.
Each recognizer is called directly with nlp_artifacts=None. Needs the models dependency group."""
from __future__ import annotations

from steward_gateway.redact import Span
from steward_gateway.redact.patterns import DOB, LONG, SSN, secrets

TOKENS = {"EMAIL_ADDRESS": "[email]", "PHONE_NUMBER": "[phone]", "US_SSN": "[ssn]", "CREDIT_CARD": "[card number]",
          "ABA_ROUTING_NUMBER": "[routing number]", "IBAN_CODE": "[iban]", "DATE_OF_BIRTH": "[date of birth]",
          "ACCOUNT_NUMBER": "[account number]"}


class PresidioDetector:
    name = "presidio"

    def __init__(self):
        from presidio_analyzer import Pattern, PatternRecognizer
        from presidio_analyzer.predefined_recognizers import (
            AbaRoutingRecognizer, CreditCardRecognizer, EmailRecognizer, IbanRecognizer, PhoneRecognizer,
            UsSsnRecognizer,
        )
        self.recognizers = [
            EmailRecognizer(), PhoneRecognizer(), UsSsnRecognizer(), CreditCardRecognizer(), AbaRoutingRecognizer(),
            IbanRecognizer(),
            PatternRecognizer(supported_entity="US_SSN", name="AnySsnShape", patterns=[Pattern("ssn", SSN.pattern, 0.5)]),
            PatternRecognizer(supported_entity="DATE_OF_BIRTH", patterns=[Pattern("dob", DOB.pattern, 0.6)]),
            PatternRecognizer(supported_entity="ACCOUNT_NUMBER", patterns=[Pattern("long", LONG.pattern, 0.4)]),
        ]

    def detect(self, text: str) -> list[Span]:
        out = []
        for r in self.recognizers:
            for res in r.analyze(text=text, entities=r.supported_entities, nlp_artifacts=None) or []:
                out.append(Span(res.start, res.end, TOKENS[res.entity_type], "presidio"))
        return out + secrets(text)
