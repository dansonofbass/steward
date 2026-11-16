import base64
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Request, Response


@dataclass
class _Acct:
    conn_id: str; conn_name: str; org_id: str; id: str; name: str
    balance_cents: int; balance_date: int; txns: list


@dataclass
class FakeState:
    accounts: list[_Acct] = field(default_factory=list)
    errlist: list[dict] = field(default_factory=list)
    v1_errors: list[str] = field(default_factory=list)
    fail_conn: str | None = None
    claimed: set = field(default_factory=set)
    calls: list[dict] = field(default_factory=list)
    holdings: dict = field(default_factory=dict)  # SimpleFIN account id -> its holdings list

    def add_account(self, conn_id, conn_name, org_id, acct_id, balance_cents, balance_date_epoch, txns=(), name=None):
        self.accounts.append(_Acct(conn_id, conn_name, org_id, acct_id, name or acct_id,
                                   balance_cents, balance_date_epoch, list(txns)))

    def payload(self, start: int | None, pending: bool) -> dict:
        conns, accts, errs = {}, [], list(self.errlist)
        failed: set = set()
        for a in self.accounts:
            if a.conn_id == self.fail_conn:
                if a.conn_id not in failed:
                    failed.add(a.conn_id)
                    errs.append({"code": "con.auth", "msg": "Please re-authenticate", "conn_id": a.conn_id})
                continue
            conns[a.conn_id] = {"conn_id": a.conn_id, "name": a.conn_name, "org_id": a.org_id, "sfin_url": "x"}
            txns = []
            for t in a.txns:
                tid, posted, cents, desc, *rest = t
                is_pending = bool(rest and rest[0])
                if is_pending and not pending:
                    continue
                if start is not None and posted and posted < start:
                    continue
                txns.append({"id": tid, "posted": posted, "amount": f"{cents / 100:.2f}", "description": desc,
                             "pending": is_pending})
            acct = {"id": a.id, "name": a.name, "conn_id": a.conn_id, "currency": "USD",
                    "balance": f"{a.balance_cents / 100:.2f}", "balance-date": a.balance_date,
                    "transactions": txns}
            if a.id in self.holdings:
                acct["holdings"] = self.holdings[a.id]
            accts.append(acct)
        extra = {"errors": list(self.v1_errors)} if self.v1_errors else {}
        return {**extra, "errlist": errs, "connections": list(conns.values()), "accounts": accts}


def make_fake():
    state = FakeState()
    app = FastAPI()

    @app.post("/claim/{token}")
    def claim(token: str):
        if token in state.claimed:
            raise HTTPException(403)
        state.claimed.add(token)
        return Response("http://demo:demo@testserver/simplefin", media_type="text/plain")

    @app.get("/simplefin/accounts")
    def accounts(request: Request):
        auth = request.headers.get("authorization", "")
        if auth != "Basic " + base64.b64encode(b"demo:demo").decode():
            raise HTTPException(403)
        q = request.query_params
        if q.get("version") != "2":
            return Response('{"error": "version required"}', status_code=400, media_type="application/json")
        state.calls.append(dict(q))
        start = int(q["start-date"]) if "start-date" in q else None
        return state.payload(start, q.get("pending") == "1")

    return app, state
