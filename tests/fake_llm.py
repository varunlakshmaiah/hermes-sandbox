"""Minimal OpenAI-compatible chat server for the smoke test. Records each request.

Usage: fake_llm.py PORT LOG_FILE
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "fake-llm-reply"


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def record(self, body=None):
        entry = {"path": self.path, "authorization": self.headers.get("Authorization"), "body": body}
        with open(sys.argv[2], "a") as log:
            log.write(json.dumps(entry) + "\n")

    def do_GET(self):
        self.record()
        if self.path.rstrip("/").endswith("/models"):
            self.send(
                200,
                json.dumps({"object": "list", "data": [{"id": "smoke-model", "object": "model"}]}).encode(),
            )
        else:
            self.send(404, b"{}")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        self.record(body)
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self.send(404, b"{}")
            return
        base = {"id": "chatcmpl-smoke", "created": int(time.time()), "model": body.get("model", "")}
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if not body.get("stream"):
            message = {"role": "assistant", "content": REPLY}
            choice = {"index": 0, "message": message, "finish_reason": "stop"}
            self.send(
                200,
                json.dumps(
                    {**base, "object": "chat.completion", "choices": [choice], "usage": usage}
                ).encode(),
            )
            return
        chunks = [
            {"index": 0, "delta": {"role": "assistant", "content": REPLY}, "finish_reason": None},
            {"index": 0, "delta": {}, "finish_reason": "stop"},
        ]
        events = [
            {
                **base,
                "object": "chat.completion.chunk",
                "choices": [choice],
                **({"usage": usage} if i else {}),
            }
            for i, choice in enumerate(chunks)
        ]
        stream = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        self.send(200, stream.encode(), "text/event-stream")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
