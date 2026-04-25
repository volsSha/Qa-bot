import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qa_bot.config import Settings
from qa_bot.llm_evaluator import EVALUATION_CATEGORIES, LLMEvaluator
from qa_bot.models import (
    CheckResult,
    LLMEvaluation,
    PageSnapshot,
    PreprocessedPage,
    Severity,
)

NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)


def _make_settings(**overrides) -> Settings:
    defaults = {
        "openrouter_api_key": "test-key",
        "llm_model": "openai/gpt-4",
        "text_content_max_chars": 4000,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_snapshot(url: str = "https://example.com") -> PageSnapshot:
    return PageSnapshot(
        url=url,
        html="<html><body>Hello</body></html>",
        screenshot=b"fake-png",
        text_content="Hello world",
        console_errors=[],
        load_time_ms=200,
        status_code=200,
        fetched_at=NOW,
    )


def _make_preprocessed(text_content: str = "Hello world") -> PreprocessedPage:
    return PreprocessedPage(
        title="Example",
        text_content=text_content,
        images=[],
        links=[],
        forms=[],
        meta_tags={},
        headings=[],
    )


def _make_rule_result(
    severity: str = Severity.PASS, message: str = "OK"
) -> CheckResult:
    return CheckResult(
        check_name="test_check",
        severity=severity,
        message=message,
        evidence=None,
        category="test",
    )


def _make_findings_json() -> dict:
    findings = []
    for cat in EVALUATION_CATEGORIES:
        findings.append(
            {
                "category": cat,
                "passed": True,
                "confidence": 0.9,
                "evidence": f"All good for {cat}",
                "recommendation": None,
            }
        )
    return {"findings": findings}


def _mock_response(content: str, model: str = "openai/gpt-4") -> MagicMock:
    choice_msg = MagicMock()
    choice_msg.content = content
    choice = MagicMock()
    choice.message = choice_msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.model = model
    return resp


@pytest.fixture
def settings() -> Settings:
    return _make_settings()


@pytest.fixture
def evaluator(settings: Settings) -> LLMEvaluator:
    return LLMEvaluator(settings)


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_evaluation_with_five_findings(
        self, evaluator: LLMEvaluator, settings: Settings
    ):
        payload = _make_findings_json()
        mock_resp = _mock_response(json.dumps(payload))

        with patch(
            "qa_bot.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [_make_rule_result()],
                )

        assert isinstance(result, LLMEvaluation)
        assert result.model == "openai/gpt-4"
        assert len(result.findings) == 5
        categories = {f.category for f in result.findings}
        assert categories == set(EVALUATION_CATEGORIES)
        for finding in result.findings:
            assert finding.passed is True
            assert finding.confidence == 0.9
            assert "All good" in finding.evidence
        assert result.evaluated_at == NOW


class TestTextTruncation:
    @pytest.mark.asyncio
    async def test_text_truncated_to_max_chars(self, evaluator: LLMEvaluator):
        long_text = "x" * 10000
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
            "qa_bot.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(text_content=long_text),
                    [],
                )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            user_msg = messages[1]
            text_part = user_msg.content[0].text
            assert len(text_part) < 10000
            assert "Cleaned Text Content" in text_part


class TestMalformedJson:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_error_finding(
        self, evaluator: LLMEvaluator, settings: Settings
    ):
        mock_resp = _mock_response("this is not json {{{")

        with patch(
            "qa_bot.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert result.model == settings.llm_model
        assert len(result.findings) == 1
        assert result.findings[0].category == "error"
        assert result.findings[0].passed is False
        assert result.findings[0].confidence == 1.0
        assert "parse" in result.findings[0].evidence.lower()


class TestRateLimitRetry:
    @pytest.mark.asyncio
    async def test_429_retries_then_succeeds(self, evaluator: LLMEvaluator):
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp_mock = httpx.Response(
                    429,
                    request=httpx.Request(
                        "POST",
                        "https://openrouter.ai/api/v1/chat/completions",
                    ),
                )
                raise httpx.HTTPStatusError(
                    "Rate limited",
                    request=resp_mock.request,
                    response=resp_mock,
                )
            return mock_resp

        with patch(
            "qa_bot.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert call_count == 2
        assert len(result.findings) == 5


class TestTimeoutRetry:
    @pytest.mark.asyncio
    async def test_timeout_returns_error_after_retries(
        self, evaluator: LLMEvaluator, settings: Settings
    ):
        async def always_timeout(*args, **kwargs):
            raise httpx.ReadTimeout("Request timed out")

        with patch(
            "qa_bot.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=always_timeout)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert result.model == settings.llm_model
        assert len(result.findings) == 1
        assert result.findings[0].category == "error"
        assert result.findings[0].passed is False


class TestPromptConstruction:
    @pytest.mark.asyncio
    async def test_system_prompt_present(self, evaluator: LLMEvaluator):
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
            "qa_bot.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await evaluator.evaluate(
                    _make_snapshot(url="https://test.com"),
                    _make_preprocessed(text_content="Some content"),
                    [_make_rule_result(severity=Severity.WARNING, message="Alt text missing")],
                )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]

            assert len(messages) == 2
            assert messages[0].role == "system"
            assert "QA analyst" in messages[0].content
            assert messages[1].role == "user"

            user_text = messages[1].content[0].text
            assert "https://test.com" in user_text
            assert "WARNING" in user_text
            assert "Alt text missing" in user_text
            assert "Some content" in user_text

            image_part = messages[1].content[1]
            assert image_part.type == "image_url"
            assert image_part.image_url.url.startswith("data:image/png;base64,")
