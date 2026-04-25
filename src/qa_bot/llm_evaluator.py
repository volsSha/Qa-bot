import base64
import json
import logging
from datetime import UTC, datetime

import openrouter
from openrouter.components.chatformatjsonschemaconfig import (
    ChatFormatJSONSchemaConfig,
)
from openrouter.components.chatjsonschemaconfig import ChatJSONSchemaConfig
from openrouter.components.chatsystemmessage import ChatSystemMessage
from openrouter.components.chatusermessage import ChatUserMessage
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from qa_bot.config import Settings
from qa_bot.models import (
    CheckResult,
    LLMEvaluation,
    LLMFinding,
    PageSnapshot,
    PreprocessedPage,
)

logger = logging.getLogger(__name__)

EVALUATION_CATEGORIES = [
    "layout_quality",
    "content_coherence",
    "visual_anomalies",
    "placeholder_detection",
    "navigation_logic",
]

SYSTEM_PROMPT = (
    "You are a QA analyst evaluating web pages. "
    "For each category, answer whether the page passes and cite specific evidence."
)

RESPONSE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                    "recommendation": {"type": "string"},
                },
                "required": [
                    "category",
                    "passed",
                    "confidence",
                    "evidence",
                    "recommendation",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


def _is_retryable(exc: BaseException) -> bool:
    import httpx

    if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError)):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and (exc.response.status_code == 429 or exc.response.status_code >= 500)
    )


class LLMEvaluator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _build_response_format(self) -> ChatFormatJSONSchemaConfig:
        schema = ChatJSONSchemaConfig(
            name="findings",
            strict=True,
            schema_=RESPONSE_JSON_SCHEMA,
        )
        return ChatFormatJSONSchemaConfig(type="json_schema", json_schema=schema)

    def _build_messages(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
    ) -> list:
        non_pass_rules = [r for r in rule_results if r.severity != "pass"]
        rules_summary = "\n".join(
            f"- [{r.severity.upper()}] {r.message}" for r in non_pass_rules
        )
        truncated_text = preprocessed.text_content[: self._settings.text_content_max_chars]

        b64_screenshot = base64.b64encode(snapshot.screenshot).decode("ascii")

        user_content = [
            {
                "type": "text",
                "text": (
                    f"Page URL: {snapshot.url}\n\n"
                    f"Rule Check Results:\n"
                    f"{rules_summary if rules_summary else 'All rules passed.'}\n\n"
                    f"Cleaned Text Content:\n{truncated_text}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64_screenshot}",
                },
            },
        ]

        return [
            ChatSystemMessage(role="system", content=SYSTEM_PROMPT),
            ChatUserMessage(role="user", content=user_content),
        ]

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    async def _call_llm(self, messages: list) -> openrouter.components.ChatResult:
        async with openrouter.OpenRouter(
            api_key=self._settings.openrouter_api_key.get_secret_value(),
        ) as client:
            response = await client.chat.send_async(
                messages=messages,
                model=self._settings.llm_model,
                response_format=self._build_response_format(),
            )
            return response

    async def evaluate(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
    ) -> LLMEvaluation:
        messages = self._build_messages(snapshot, preprocessed, rule_results)

        try:
            response = await self._call_llm(messages)
            raw_content = response.choices[0].message.content
            raw_response = raw_content if isinstance(raw_content, str) else json.dumps(raw_content)
            data = json.loads(raw_response)

            findings = [
                LLMFinding(
                    category=f["category"],
                    passed=f["passed"],
                    confidence=f["confidence"],
                    evidence=f["evidence"],
                    recommendation=f.get("recommendation"),
                )
                for f in data.get("findings", [])
            ]

            return LLMEvaluation(
                model=response.model,
                findings=findings,
                raw_response=raw_response,
                evaluated_at=datetime.now(UTC),
            )
        except (json.JSONDecodeError, KeyError, TypeError, IndexError, ValueError) as exc:
            logger.warning("Failed to parse LLM response: %s", exc)
            return LLMEvaluation(
                model=self._settings.llm_model,
                findings=[
                    LLMFinding(
                        category="error",
                        passed=False,
                        confidence=1.0,
                        evidence=f"Failed to parse LLM response: {exc}",
                        recommendation=None,
                    )
                ],
                raw_response=str(exc),
                evaluated_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.error("LLM evaluation failed: %s", exc)
            return LLMEvaluation(
                model=self._settings.llm_model,
                findings=[
                    LLMFinding(
                        category="error",
                        passed=False,
                        confidence=1.0,
                        evidence=f"LLM API error: {exc}",
                        recommendation=None,
                    )
                ],
                raw_response=str(exc),
                evaluated_at=datetime.now(UTC),
            )
