"""Helpers for pipeline integration tests."""

import json

import httpx

from tests.conftest import chat_json

SUMMARIZER_MARK = "You compress conversation history"


def hist(n):
    msgs = [{"role": "system", "content": "SYS"}]
    for k in range(n):
        msgs.append({"role": "user" if k % 2 == 0 else "assistant", "content": f"m{k}"})
    return msgs


class Upstream:
    """respx side effect: summarizer -> SUMMARY TEXT, judge model -> judge_text, else ok."""

    def __init__(self, summary="SUMMARY TEXT", judge_text='{"instructions": []}',
                 summarizer_status=200, judge_status=200):
        self.summary, self.judge_text = summary, judge_text
        self.summarizer_status, self.judge_status = summarizer_status, judge_status
        self.bodies: list[dict] = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.bodies.append(body)
        first = (body["messages"][0].get("content") or "") if body["messages"] else ""
        if body.get("model") == "judge":
            if self.judge_status != 200:
                return httpx.Response(self.judge_status, text="judge down")
            text = self.judge_text(body) if callable(self.judge_text) else self.judge_text
            return httpx.Response(200, json=chat_json(text))
        if first.startswith(SUMMARIZER_MARK):
            if self.summarizer_status != 200:
                return httpx.Response(self.summarizer_status, text="down")
            return httpx.Response(200, json=chat_json(self.summary))
        return httpx.Response(200, json=chat_json("ok"))

    def agent_bodies(self):
        return [b for b in self.bodies if b.get("model") != "judge"
                and not (b["messages"][0].get("content") or "").startswith(SUMMARIZER_MARK)]

    def summarizer_calls(self):
        return [b for b in self.bodies
                if (b["messages"][0].get("content") or "").startswith(SUMMARIZER_MARK)]
