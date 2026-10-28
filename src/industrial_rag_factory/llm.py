"""DeepSeek JSON-completion adapter. Exact API model identifier is configurable."""
from __future__ import annotations
import json
from .prompts import SYSTEM_ANSWER_V1


class DeepSeekGenerator:
    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY required")
        if not base_url.startswith("https://"):
            raise ValueError("DeepSeek base URL must use HTTPS")
        self.api_key,self.base_url,self.model = api_key,base_url,model

    def generate(self, question: str, evidence: list[tuple[str,str]]) -> dict:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install industrial-rag-factory[llm]") from exc
        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30.0, max_retries=1)
        context = "\n\n".join(f"[{key}] {value[:3500]}" for key,value in evidence)
        completion = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role":"system","content":SYSTEM_ANSWER_V1},
                {"role":"user","content":f"Question: {question}\n\nUNTRUSTED EVIDENCE:\n{context}"},
            ],
            response_format={"type":"json_object"},
            temperature=0,
            max_tokens=1200,
        )
        choice = completion.choices[0]
        if choice.finish_reason == "length" or not choice.message.content:
            raise ValueError("Empty or truncated DeepSeek JSON output")
        payload = json.loads(choice.message.content)
        if not isinstance(payload,dict) or not isinstance(payload.get("answer"),str):
            raise ValueError("Invalid DeepSeek JSON structure")
        if not isinstance(payload.get("abstain"),bool) or not isinstance(payload.get("citation_ids"),list):
            raise ValueError("Invalid DeepSeek response fields")
        return payload
