"""The synthetic statements for the NAS's tests, built once a session in memory (never written to disk)."""
from __future__ import annotations

import copy
from datetime import date
from functools import lru_cache

from steward_gateway.evals.statement_set import Truth, build


@lru_cache(maxsize=None)
def pdf(sid: str, variant: str | None = None, end: date | None = None) -> tuple[bytes, Truth]:
    return build(sid, end, variant)


@lru_cache(maxsize=None)
def _pages(sid: str, variant: str | None) -> list[dict]:
    from steward_pdf.sandbox import read_pdf            # in-process: the child's own function
    return read_pdf(pdf(sid, variant)[0])["pages"]


def pages(sid: str, variant: str | None = None) -> list[dict]:
    """The statement's extracted pages, a fresh copy each call so no test changes another's."""
    return copy.deepcopy(_pages(sid, variant))


@lru_cache(maxsize=None)
def font_pdf(kind: str) -> bytes:
    """A one-page statement in a font the synthetic set never uses, for what the PDF libraries load only on first use:
    "cid", a CJK font that isn't embedded, whose character maps pdfminer reads from its own folder; "embedded", a
    TrueType font embedded with a ToUnicode map (UTF-16BE, as most real statements carry) and a UTF-16 title."""
    import io

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfgen import canvas
    if kind == "cid":
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        font, text = "HeiseiMin-W3", "Balance 12.50 残高"
        pdfmetrics.registerFont(UnicodeCIDFont(font))
    elif kind == "embedded":
        from reportlab.pdfbase.ttfonts import TTFont
        font, text = "Vera", "Balance 12.50 café"
        pdfmetrics.registerFont(TTFont(font, "Vera.ttf"))
    else:
        raise ValueError(kind)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 300), invariant=1)
    c.setTitle("Relevé 残高")
    c.setFont(font, 12)
    c.drawString(20, 200, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _aes(key: bytes, iv: bytes | None, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    enc = Cipher(algorithms.AES(key), modes.ECB() if iv is None else modes.CBC(iv)).encryptor()
    return enc.update(data) + enc.finalize()


def _hash_2b(password: bytes, salt: bytes, udata: bytes) -> bytes:
    """ISO 32000-2's Algorithm 2.B, the AES-256 (revision 6) password hash."""
    from hashlib import sha256, sha384, sha512
    k, n = sha256(password + salt + udata).digest(), 0
    while True:
        e = _aes(k[:16], k[16:32], (password + k + udata) * 64)
        k, n = (sha256, sha384, sha512)[sum(e[:16]) % 3](e).digest(), n + 1
        if n >= 64 and e[-1] <= n - 32:
            return k[:32]


@lru_cache(maxsize=None)
def aes_pdf() -> bytes:
    """A one-page statement encrypted with AES-256 (revision 6) under an empty user password and an owner password,
    as a bank's permissions-only file is: opened with no password, through the AES code the RC4 variants never reach."""
    import struct
    key, owner = bytes(range(32)), b"owner-only"
    uvs, uks, ovs, oks, iv = b"uvsaltuv", b"uksaltuk", b"ovsaltov", b"oksaltok", b"\x07" * 16
    u = _hash_2b(b"", uvs, b"") + uvs + uks
    o = _hash_2b(owner, ovs, u) + ovs + oks
    ue, oe = _aes(_hash_2b(b"", uks, b""), b"\0" * 16, key), _aes(_hash_2b(owner, oks, u), b"\0" * 16, key)
    perms = _aes(key, None, struct.pack("<i", -4) + b"\xff\xff\xff\xffTadb" + b"0000")
    text = b"BT /F1 12 Tf 20 100 Td (Balance 12.50) Tj ET"
    pad = 16 - len(text) % 16
    stream = iv + _aes(key, iv, text + bytes([pad]) * pad)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Filter /Standard /V 5 /R 6 /Length 256 /P -4 /StmF /StdCF /StrF /StdCF "
            b"/CF << /StdCF << /CFM /AESV3 /AuthEvent /DocOpen /Length 32 >> >> "
            b"/O <%s> /U <%s> /OE <%s> /UE <%s> /Perms <%s> >>"
            % tuple(v.hex().encode() for v in (o, u, oe, ue, perms))]
    out, at = bytearray(b"%PDF-1.7\n"), []
    for i, body in enumerate(objs, 1):
        at.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % a for a in at)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Encrypt 6 0 R /ID [<%s> <%s>] >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1, b"ab" * 16, b"ab" * 16, xref)
    return bytes(out)
