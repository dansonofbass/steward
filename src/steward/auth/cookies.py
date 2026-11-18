"""The names and flags of Steward's two cookies: the session, and the device the sign-in page marks (issue #7).

Issue #14: on an https STEWARD_BASE_URL each name takes the __Host- prefix, so the browser keeps the cookie only when
it is Secure, on path /, and has no Domain: no other host on the domain can set or shadow it. A plain-http install
(the demo on localhost) keeps the plain names, since a __Host- cookie must come over a secure connection. 0.1.0 set
the plain session name everywhere, so for the 0.1.1 release a request still signs in with it: the session is read
under the new name first and the old one second, and the answer to a request signed in with the old one moves it to
the new name (deps.current_session queues the move, MoveSession adds it to whatever answer the route gives). Every
cookie here is Secure, HttpOnly and SameSite=Lax, as the session cookie always was."""
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import Response

SESSION = "steward_session"
HOST_SESSION = "__Host-steward_session"
DEVICE = "steward_device"
HOST_DEVICE = "__Host-steward_device"
FLAGS = {"path": "/", "secure": True, "httponly": True, "samesite": "lax"}
MOVE = "steward_session_move"    # the request's state key for a queued move of 0.1.0's cookie


def https(base_url: str) -> bool:
    return urlsplit(base_url.strip()).scheme.lower() == "https"


def session_name(base_url: str) -> str:
    return HOST_SESSION if https(base_url) else SESSION


def device_name(base_url: str) -> str:
    return HOST_DEVICE if https(base_url) else DEVICE


def _base(request: Request) -> str:
    return request.app.state.settings.base_url


def read_session(request: Request) -> tuple[str | None, str | None]:
    """The session token and the name it came under: the current name first, then 0.1.0's."""
    for name in dict.fromkeys((session_name(_base(request)), SESSION)):
        token = request.cookies.get(name)
        if token:
            return token, name
    return None, None


def set_session(request: Request, response: Response, token: str, max_age: int) -> None:
    name = session_name(_base(request))
    response.set_cookie(name, token, max_age=max_age, **FLAGS)
    if name != SESSION and request.cookies.get(SESSION):
        response.delete_cookie(SESSION, **FLAGS)     # 0.1.0's name, now replaced


def clear_session(request: Request, response: Response) -> None:
    for name in dict.fromkeys((session_name(_base(request)), SESSION)):
        response.delete_cookie(name, **FLAGS)


def move_session(request: Request, token: str, max_age: int) -> None:
    """Queue the move of a 0.1.0 session cookie to the current name for MoveSession to add to the answer."""
    r = Response()
    set_session(request, r, token, max_age)
    setattr(request.state, MOVE, [(k, v) for k, v in r.raw_headers if k == b"set-cookie"])


def cancel_move(request: Request) -> None:
    """Drop a queued move: the session it would move has just ended."""
    setattr(request.state, MOVE, None)


class MoveSession:
    """Adds a queued session move to the answer, whichever answer it is. A route that returns its own Response (every
    204) drops the headers a dependency wrote on FastAPI's injected one, so the move rides here instead. Pure ASGI."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        state = scope.setdefault("state", {})   # the dict request.state writes to, made here so a copied scope shares it

        async def sending(message):
            if message["type"] == "http.response.start" and state.get(MOVE):
                message = {**message, "headers": [*message.get("headers", []), *state[MOVE]]}
            await send(message)
        await self.app(scope, receive, sending)
