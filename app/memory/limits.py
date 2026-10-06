import os


class MemoryPayloadLimit:
    """Reject oversized memory request bodies before JSON/Pydantic allocates them."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in ("/v1/memories/add", "/v1/memories/search"):
            return await self.app(scope, receive, send)
        try:
            limit = int(os.getenv("MEMORY_MAX_PAYLOAD_BYTES", "8388608"))
            if limit < 1024:
                raise ValueError()
        except ValueError:
            limit = 8388608
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"memory_payload_too_large"}'})
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
