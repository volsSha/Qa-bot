import base64
import io
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import openrouter
from openrouter.components.chatformatjsonschemaconfig import (
    ChatFormatJSONSchemaConfig,
)
from openrouter.components.chatjsonschemaconfig import ChatJSONSchemaConfig
from openrouter.components.chatsystemmessage import ChatSystemMessage
from openrouter.components.chatusermessage import ChatUserMessage
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from qa_bot.config import Settings
from qa_bot.domain.models import (
    CheckResult,
    HistoricalContext,
    LLMEvaluation,
    LLMFinding,
    PageSnapshot,
    PreprocessedPage,
)

logger = logging.getLogger(__name__)

VISION_CATEGORIES = [
    "layout_quality",
    "visual_anomalies",
    "placeholder_detection",
    "visual_regression",
    "layout_drift",
    "content_consistency",
]

TEXT_CATEGORIES = [
    "content_coherence",
    "navigation_logic",
]

EVALUATION_CATEGORIES = VISION_CATEGORIES + TEXT_CATEGORIES

VISION_SYSTEM_PROMPT = (
    "You are a visual QA analyst evaluating web page screenshots. "
    "Analyze the screenshot(s) for visual quality, layout issues, broken elements, "
    "placeholder content, and visual regressions compared to previous screenshots. "
    "For each category, answer whether the page passes and cite specific evidence."
)

TEXT_SYSTEM_PROMPT = (
    "You are a QA analyst evaluating web pages. "
    "Based on the rule check results, console errors, page text content, "
    "and visual analysis findings, evaluate content coherence and navigation logic. "
    "Determine whether the page is functioning correctly. "
    "For each category, answer whether the page passes and cite specific evidence."
)

SINGLE_SYSTEM_PROMPT = (
    "You are a QA analyst evaluating web pages. "
    "For each category, answer whether the page passes and cite specific evidence. "
    "When previous screenshots are provided, compare them with the current screenshot "
    "to detect visual regressions, layout drift, and content changes."
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
    if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError)):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and (exc.response.status_code == 429 or exc.response.status_code >= 500)
    )


def _resize_screenshot(screenshot_bytes: bytes, max_width: int) -> bytes:
    img = Image.open(io.BytesIO(screenshot_bytes))
    if img.width <= max_width:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    ratio = max_width / img.width
    new_height = int(img.height * ratio)
    resized = img.resize((max_width, new_height))
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    return buf.getvalue()


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

    def _build_vision_messages(
        self,
        snapshot: PageSnapshot,
        historical_contexts: list[HistoricalContext] | None = None,
    ) -> list:
        b64_screenshot = base64.b64encode(snapshot.screenshot).decode("ascii")

        user_content = [
            {
                "type": "text",
                "text": f"Page URL: {snapshot.url}\n\nAnalyze this web page screenshot for visual quality.",
            },
            {
                "type": "text",
                "text": "CURRENT SCREENSHOT:",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64_screenshot}",
                },
            },
        ]

        if historical_contexts:
            for ctx in historical_contexts:
                screenshot_bytes = self._load_historical_screenshot(ctx.screenshot_path)
                if screenshot_bytes is None:
                    continue
                resized = _resize_screenshot(
                    screenshot_bytes, self._settings.screenshot_history_max_width
                )
                b64_hist = base64.b64encode(resized).decode("ascii")
                age_label = ""
                if ctx.previous_scanned_at:
                    delta = datetime.now(UTC) - ctx.previous_scanned_at
                    if delta.days > 0:
                        age_label = f" ({delta.days}d ago"
                    else:
                        hours = delta.seconds // 3600
                        age_label = f" ({hours}h ago"
                    if ctx.previous_health_score is not None:
                        age_label += f", score: {ctx.previous_health_score:.0f}"
                    age_label += ")"
                user_content.append(
                    {
                        "type": "text",
                        "text": f"PREVIOUS SCREENSHOT{age_label}:",
                    }
                )
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_hist}",
                        },
                    }
                )

        return [
            ChatSystemMessage(role="system", content=VISION_SYSTEM_PROMPT),
            ChatUserMessage(role="user", content=user_content),
        ]

    def _build_text_messages(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
        vision_findings: list[LLMFinding] | None = None,
    ) -> list:
        non_pass_rules = [r for r in rule_results if r.severity != "pass"]
        rules_summary = "\n".join(
            f"- [{r.severity.upper()}] {r.message}" for r in non_pass_rules
        )
        truncated_text = preprocessed.text_content[: self._settings.text_content_max_chars]

        parts = [
            f"Page URL: {snapshot.url}\n\n",
            f"Rule Check Results:\n",
            f"{rules_summary if rules_summary else 'All rules passed.'}\n\n",
        ]

        if snapshot.console_errors:
            console_summary = "\n".join(f"- {e}" for e in snapshot.console_errors[:20])
            parts.append(f"Console Errors:\n{console_summary}\n\n")

        if vision_findings:
            parts.append("Visual Analysis Findings (from vision model):\n")
            for f in vision_findings:
                status = "PASS" if f.passed else "FAIL"
                parts.append(f"- [{status}] {f.category}: {f.evidence}\n")
            parts.append("\n")

        parts.append(f"Cleaned Text Content:\n{truncated_text}")

        user_content = [{"type": "text", "text": "".join(parts)}]

        return [
            ChatSystemMessage(role="system", content=TEXT_SYSTEM_PROMPT),
            ChatUserMessage(role="user", content=user_content),
        ]

    def _build_messages(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
        historical_contexts: list[HistoricalContext] | None = None,
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
                "type": "text",
                "text": "CURRENT SCREENSHOT:",
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64_screenshot}",
                },
            },
        ]

        if historical_contexts:
            for ctx in historical_contexts:
                screenshot_bytes = self._load_historical_screenshot(ctx.screenshot_path)
                if screenshot_bytes is None:
                    continue
                resized = _resize_screenshot(
                    screenshot_bytes, self._settings.screenshot_history_max_width
                )
                b64_hist = base64.b64encode(resized).decode("ascii")
                age_label = ""
                if ctx.previous_scanned_at:
                    delta = datetime.now(UTC) - ctx.previous_scanned_at
                    if delta.days > 0:
                        age_label = f" ({delta.days}d ago"
                    else:
                        hours = delta.seconds // 3600
                        age_label = f" ({hours}h ago"
                    if ctx.previous_health_score is not None:
                        age_label += f", score: {ctx.previous_health_score:.0f}"
                    age_label += ")"
                user_content.append(
                    {
                        "type": "text",
                        "text": f"PREVIOUS SCREENSHOT{age_label}:",
                    }
                )
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64_hist}",
                        },
                    }
                )
                if ctx.previous_findings_summary:
                    user_content.append(
                        {
                            "type": "text",
                            "text": f"Previous scan summary: {ctx.previous_findings_summary}",
                        }
                    )

        return [
            ChatSystemMessage(role="system", content=SINGLE_SYSTEM_PROMPT),
            ChatUserMessage(role="user", content=user_content),
        ]

    def _load_historical_screenshot(self, screenshot_path: str | None) -> bytes | None:
        if screenshot_path is None:
            return None
        path = Path(screenshot_path)
        if not path.exists():
            logger.warning("Historical screenshot not found: %s", screenshot_path)
            return None
        data = path.read_bytes()
        if not data:
            logger.warning("Empty screenshot file: %s", screenshot_path)
            return None
        return data

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    async def _call_llm(self, messages: list, model: str) -> openrouter.components.ChatResult:
        async with openrouter.OpenRouter(
            api_key=self._settings.openrouter_api_key.get_secret_value(),
        ) as client:
            response = await client.chat.send_async(
                messages=messages,
                model=model,
                response_format=self._build_response_format(),
            )
            return response

    def _parse_findings(self, raw_content: str) -> list[LLMFinding] | None:
        data = json.loads(raw_content)
        return [
            LLMFinding(
                category=f["category"],
                passed=f["passed"],
                confidence=f["confidence"],
                evidence=f["evidence"],
                recommendation=f.get("recommendation"),
            )
            for f in data.get("findings", [])
        ]

    def _make_error_evaluation(
        self, model: str, exc: Exception, now: datetime
    ) -> LLMEvaluation:
        return LLMEvaluation(
            model=model,
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
            evaluated_at=now,
        )

    async def _evaluate_single(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
        historical_contexts: list[HistoricalContext] | None,
    ) -> LLMEvaluation:
        messages = self._build_messages(
            snapshot, preprocessed, rule_results, historical_contexts
        )
        response = await self._call_llm(messages, self._settings.llm_model)
        raw_content = response.choices[0].message.content
        raw_response = raw_content if isinstance(raw_content, str) else json.dumps(raw_content)
        findings = self._parse_findings(raw_response) or []
        return LLMEvaluation(
            model=response.model,
            findings=findings,
            raw_response=raw_response,
            evaluated_at=datetime.now(UTC),
        )

    async def _evaluate_dual(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
        historical_contexts: list[HistoricalContext] | None,
    ) -> LLMEvaluation:
        vision_model = self._settings.llm_vision_model
        text_model = self._settings.llm_text_model
        now = datetime.now(UTC)

        vision_findings: list[LLMFinding] = []
        try:
            vision_messages = self._build_vision_messages(snapshot, historical_contexts)
            vision_response = await self._call_llm(vision_messages, vision_model)
            raw = vision_response.choices[0].message.content
            raw_str = raw if isinstance(raw, str) else json.dumps(raw)
            vision_findings = self._parse_findings(raw_str) or []
        except Exception as exc:
            logger.warning("Vision model call failed, continuing with text-only: %s", exc)

        text_findings: list[LLMFinding] = []
        try:
            text_messages = self._build_text_messages(
                snapshot, preprocessed, rule_results, vision_findings
            )
            text_response = await self._call_llm(text_messages, text_model)
            raw = text_response.choices[0].message.content
            raw_str = raw if isinstance(raw, str) else json.dumps(raw)
            text_findings = self._parse_findings(raw_str) or []
        except Exception as exc:
            logger.error("Text model call failed: %s", exc)
            return self._make_error_evaluation(
                f"{vision_model} + {text_model}", exc, now
            )

        all_findings = vision_findings + text_findings
        model_label = f"{vision_model} + {text_model}"
        return LLMEvaluation(
            model=model_label,
            findings=all_findings,
            raw_response="",
            evaluated_at=now,
        )

    async def evaluate(
        self,
        snapshot: PageSnapshot,
        preprocessed: PreprocessedPage,
        rule_results: list[CheckResult],
        historical_contexts: list[HistoricalContext] | None = None,
    ) -> LLMEvaluation:
        try:
            if self._settings.is_dual_model:
                return await self._evaluate_dual(
                    snapshot, preprocessed, rule_results, historical_contexts
                )
            return await self._evaluate_single(
                snapshot, preprocessed, rule_results, historical_contexts
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
