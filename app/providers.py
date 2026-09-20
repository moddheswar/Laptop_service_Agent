import json
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from . import config

@dataclass
class ModelResponse:
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)  # [{"id","name","args"}]

class Provider(Protocol):
    def respond(self, history: list[dict], system_prompt: str, tools: list[dict]) -> ModelResponse: ...

class GeminiProvider:
    """Native Gemini function-calling provider (google-genai SDK)."""

    def __init__(self, model=None, api_key=None):
        if not (api_key or config.GEMINI_API_KEY):
            raise RuntimeError("Set GEMINI_API_KEY in .env")
        from google import genai
        self.client = genai.Client(api_key=api_key or config.GEMINI_API_KEY)
        self.model = model or config.GEMINI_MODEL

    # ---- translation: our normalized history -> Gemini Contents ----
    @staticmethod
    def _contents(history):
        from google.genai import types
        contents = []
        for m in history:
            if m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
            elif m["role"] == "assistant":
                parts = []
                for tc in m.get("tool_calls", []):
                    parts.append(types.Part(function_call=types.FunctionCall(name=tc["name"], args=tc["args"])))
                if m.get("content"):
                    parts.append(types.Part(text=m["content"]))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif m["role"] == "tool":
                contents.append(types.Content(role="user", parts=[types.Part(
                    function_response=types.FunctionResponse(
                        name=m["tool_name"],
                        response=json.loads(m["content"] or "{}"),
                    ))]))
        return contents

    @staticmethod
    def _declarations(tools):
        from google.genai import types
        return [types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"]["description"],
                parameters=t["function"]["parameters"],
            ) for t in tools
        ])]

    def respond(self, history, system_prompt, tools):
        from google.genai import types
        resp = self.client.models.generate_content(
            model=self.model,
            contents=self._contents(history),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=self._declarations(tools),
                temperature=0,
            ),
        )
        calls = [
            {"id": f"call_{uuid.uuid4().hex[:12]}", "name": fc.name, "args": dict(fc.args or {})}
            for fc in (resp.function_calls or [])
        ]
        return ModelResponse(content=resp.text or None, tool_calls=calls)

def get_provider():
    return GeminiProvider()