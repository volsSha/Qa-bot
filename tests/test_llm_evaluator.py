import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qa_bot.config import Settings
from qa_bot.domain.models import (
    CheckResult,
    HistoricalContext,
    LLMEvaluation,
    PageSnapshot,
    PreprocessedPage,
    Severity,
)
from qa_bot.services.llm_evaluator import (
    EVALUATION_CATEGORIES,
    TEXT_CATEGORIES,
    VISION_CATEGORIES,
    LLMEvaluator,
)

NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC)


def _make_settings(**overrides) -> Settings:
    defaults = {
        "openrouter_api_key": "test-key",
        "llm_model": "openai/gpt-4",
        "llm_vision_model": None,
        "llm_text_model": None,
        "text_content_max_chars": 4000,
        "screenshot_history_depth": 2,
        "screenshot_history_max_width": 640,
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


def _make_findings_json(categories: list[str] | None = None) -> dict:
    cats = categories or EVALUATION_CATEGORIES
    findings = []
    for cat in cats:
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
    async def test_returns_evaluation_with_all_findings(
        self, evaluator: LLMEvaluator, settings: Settings
    ):
        payload = _make_findings_json()
        mock_resp = _mock_response(json.dumps(payload))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [_make_rule_result()],
                )

        assert isinstance(result, LLMEvaluation)
        assert result.model == "openai/gpt-4"
        assert len(result.findings) == 8
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
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
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
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
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
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert call_count == 2
        assert len(result.findings) == 8


class TestTimeoutRetry:
    @pytest.mark.asyncio
    async def test_timeout_returns_error_after_retries(
        self, evaluator: LLMEvaluator, settings: Settings
    ):
        async def always_timeout(*args, **kwargs):
            raise httpx.ReadTimeout("Request timed out")

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=always_timeout)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
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
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
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

            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 1
            assert image_parts[0].image_url.url.startswith("data:image/png;base64,")

    @pytest.mark.asyncio
    async def test_no_historical_screenshots_by_default(self, evaluator: LLMEvaluator):
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 1


class TestMultiImage:
    @pytest.mark.asyncio
    async def test_historical_screenshots_included(self, evaluator: LLMEvaluator, tmp_path):
        hist_screenshot = tmp_path / "prev.png"
        hist_screenshot.write_bytes(b"prev-png-data")

        ctx = HistoricalContext(
            previous_findings_summary="1 warning found",
            previous_health_score=85.0,
            previous_scanned_at=NOW,
            screenshot_path=str(hist_screenshot),
        )
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                with patch(
                    "qa_bot.services.llm_evaluator._resize_screenshot",
                    side_effect=lambda b, w: b,
                ):
                    await evaluator.evaluate(
                        _make_snapshot(),
                        _make_preprocessed(),
                        [],
                        historical_contexts=[ctx],
                    )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 2

    @pytest.mark.asyncio
    async def test_missing_historical_screenshot_skipped(self, evaluator: LLMEvaluator):
        ctx = HistoricalContext(
            previous_findings_summary="All good",
            previous_health_score=90.0,
            previous_scanned_at=NOW,
            screenshot_path="/nonexistent/path.png",
        )
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                    historical_contexts=[ctx],
                )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 1

    @pytest.mark.asyncio
    async def test_none_screenshot_path_skipped(self, evaluator: LLMEvaluator):
        ctx = HistoricalContext(
            previous_findings_summary="All good",
        )
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                    historical_contexts=[ctx],
                )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 1

    @pytest.mark.asyncio
    async def test_empty_historical_contexts_list(self, evaluator: LLMEvaluator):
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                    historical_contexts=[],
                )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 1

    @pytest.mark.asyncio
    async def test_multiple_historical_screenshots(self, evaluator: LLMEvaluator, tmp_path):
        paths = []
        for i in range(2):
            p = tmp_path / f"prev_{i}.png"
            p.write_bytes(f"prev-png-{i}".encode())
            paths.append(str(p))

        contexts = [
            HistoricalContext(
                previous_findings_summary=f"Scan {i}",
                previous_health_score=80.0 + i,
                previous_scanned_at=NOW,
                screenshot_path=paths[i],
            )
            for i in range(2)
        ]
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                with patch(
                    "qa_bot.services.llm_evaluator._resize_screenshot",
                    side_effect=lambda b, w: b,
                ):
                    await evaluator.evaluate(
                        _make_snapshot(),
                        _make_preprocessed(),
                        [],
                        historical_contexts=contexts,
                    )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            image_parts = [
                p for p in messages[1].content if hasattr(p, "type") and p.type == "image_url"
            ]
            assert len(image_parts) == 3

    @pytest.mark.asyncio
    async def test_previous_summary_included_in_message(
        self, evaluator: LLMEvaluator, tmp_path
    ):
        hist_screenshot = tmp_path / "prev.png"
        hist_screenshot.write_bytes(b"prev-png-data")

        ctx = HistoricalContext(
            previous_findings_summary="2 warnings: slow load, missing alt",
            previous_health_score=75.0,
            previous_scanned_at=NOW,
            screenshot_path=str(hist_screenshot),
        )
        mock_resp = _mock_response(json.dumps(_make_findings_json()))

        with patch(
        "qa_bot.services.llm_evaluator.openrouter.OpenRouter"
        ) as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(return_value=mock_resp)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                with patch(
                    "qa_bot.services.llm_evaluator._resize_screenshot",
                    side_effect=lambda b, w: b,
                ):
                    await evaluator.evaluate(
                        _make_snapshot(),
                        _make_preprocessed(),
                        [],
                        historical_contexts=[ctx],
                    )

            call_args = mock_client.chat.send_async.call_args
            messages = call_args.kwargs["messages"]
            all_text = " ".join(
                p.text for p in messages[1].content if hasattr(p, "type") and p.type == "text"
            )
            assert "2 warnings: slow load, missing alt" in all_text


def _make_dual_settings(**overrides) -> Settings:
    defaults = {
        "openrouter_api_key": "test-key",
        "llm_model": "openai/gpt-4",
        "llm_vision_model": "google/gemini-2.5-flash",
        "llm_text_model": "openai/gpt-5-mini",
        "text_content_max_chars": 4000,
        "screenshot_history_depth": 2,
        "screenshot_history_max_width": 640,
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def dual_settings() -> Settings:
    return _make_dual_settings()


@pytest.fixture
def dual_evaluator(dual_settings: Settings) -> LLMEvaluator:
    return LLMEvaluator(dual_settings)


def _patch_openrouter(mock_resp, model: str | None = None):
    if model is None:
        model = "test-model"
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = mock_resp
    resp.model = model
    return patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter"), resp


def _setup_mock_or(MockOR, resp):
    mock_client = AsyncMock()
    mock_client.chat.send_async = AsyncMock(return_value=resp)
    MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    MockOR.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestDualModelHappyPath:
    @pytest.mark.asyncio
    async def test_dual_model_returns_merged_findings(self, dual_evaluator: LLMEvaluator):
        vision_payload = json.dumps(_make_findings_json(categories=VISION_CATEGORIES))
        text_payload = json.dumps(_make_findings_json(categories=TEXT_CATEGORIES))
        vision_resp = _mock_response(vision_payload, model="google/gemini-2.5-flash")
        text_resp = _mock_response(text_payload, model="openai/gpt-5-mini")

        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            call_count = 0

            async def send_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return vision_resp if call_count == 1 else text_resp

            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=send_side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await dual_evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [_make_rule_result(severity=Severity.WARNING, message="Slow load")],
                )

        assert isinstance(result, LLMEvaluation)
        assert "google/gemini-2.5-flash" in result.model
        assert "openai/gpt-5-mini" in result.model
        assert len(result.findings) == 8
        vision_cats = {f.category for f in result.findings}
        assert VISION_CATEGORIES[0] in vision_cats
        assert TEXT_CATEGORIES[0] in vision_cats

    @pytest.mark.asyncio
    async def test_dual_model_calls_separate_models(self, dual_evaluator: LLMEvaluator):
        vision_payload = json.dumps(_make_findings_json(categories=VISION_CATEGORIES))
        text_payload = json.dumps(_make_findings_json(categories=TEXT_CATEGORIES))
        vision_resp = _mock_response(vision_payload, model="google/gemini-2.5-flash")
        text_resp = _mock_response(text_payload, model="openai/gpt-5-mini")

        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            mock_client = AsyncMock()
            calls = []

            async def track_call(*args, **kwargs):
                calls.append(kwargs.get("model", args))
                return vision_resp if len(calls) == 1 else text_resp

            mock_client.chat.send_async = AsyncMock(side_effect=track_call)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await dual_evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert mock_client.chat.send_async.call_count == 2
        first_call_model = mock_client.chat.send_async.call_args_list[0].kwargs.get("model")
        second_call_model = mock_client.chat.send_async.call_args_list[1].kwargs.get("model")
        assert first_call_model == "google/gemini-2.5-flash"
        assert second_call_model == "openai/gpt-5-mini"

    @pytest.mark.asyncio
    async def test_vision_findings_passed_to_text_model(
        self, dual_evaluator: LLMEvaluator
    ):
        vision_payload = json.dumps(
            {
                "findings": [
                    {
                        "category": "layout_quality",
                        "passed": False,
                        "confidence": 0.95,
                        "evidence": "Header is misaligned",
                        "recommendation": "Fix CSS grid",
                    }
                ]
            }
        )
        text_payload = json.dumps(_make_findings_json(categories=TEXT_CATEGORIES))
        vision_resp = _mock_response(vision_payload, model="google/gemini-2.5-flash")
        text_resp = _mock_response(text_payload, model="openai/gpt-5-mini")

        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            call_count = 0

            async def send_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return vision_resp if call_count == 1 else text_resp

            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=send_side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                await dual_evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        text_call = mock_client.chat.send_async.call_args_list[1]
        text_messages = text_call.kwargs["messages"]
        text_user = text_messages[1]
        all_text = text_user.content[0].text
        assert "Visual Analysis Findings" in all_text
        assert "layout_quality" in all_text
        assert "Header is misaligned" in all_text


class TestDualModelFallback:
    @pytest.mark.asyncio
    async def test_vision_fails_text_still_runs(self, dual_evaluator: LLMEvaluator):
        text_payload = json.dumps(_make_findings_json(categories=TEXT_CATEGORIES))
        text_resp = _mock_response(text_payload, model="openai/gpt-5-mini")

        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            call_count = 0

            async def send_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                model = kwargs.get("model", "")
                if "gemini" in model:
                    raise httpx.ReadTimeout("Vision model timed out")
                return text_resp

            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=send_side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                with patch("qa_bot.services.llm_evaluator.stop_after_attempt"):
                    result = await dual_evaluator.evaluate(
                        _make_snapshot(),
                        _make_preprocessed(),
                        [],
                    )

        assert len(result.findings) == 2
        assert result.findings[0].category == "content_coherence"

    @pytest.mark.asyncio
    async def test_both_models_fail_returns_error(self, dual_evaluator: LLMEvaluator):
        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(
                side_effect=httpx.ReadTimeout("Always timeout")
            )
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await dual_evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert len(result.findings) == 1
        assert result.findings[0].category == "error"
        assert result.findings[0].passed is False

    @pytest.mark.asyncio
    async def test_text_model_malformed_json_returns_error(
        self, dual_evaluator: LLMEvaluator
    ):
        vision_payload = json.dumps(_make_findings_json(categories=VISION_CATEGORIES))
        vision_resp = _mock_response(vision_payload, model="google/gemini-2.5-flash")
        text_resp = _mock_response("not json {{{", model="openai/gpt-5-mini")

        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            call_count = 0

            async def send_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return vision_resp if call_count == 1 else text_resp

            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=send_side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                result = await dual_evaluator.evaluate(
                    _make_snapshot(),
                    _make_preprocessed(),
                    [],
                )

        assert len(result.findings) == 1
        assert result.findings[0].category == "error"
        assert result.findings[0].passed is False
        assert "llm api error" in result.findings[0].evidence.lower()


class TestDualModelConfig:
    def test_is_dual_model_true_when_both_set(self):
        s = _make_dual_settings(
            llm_vision_model="google/gemini-2.5-flash",
            llm_text_model="openai/gpt-5-mini",
        )
        assert s.is_dual_model is True

    def test_is_dual_model_false_when_only_vision_set(self):
        s = _make_dual_settings(
            llm_vision_model="google/gemini-2.5-flash",
            llm_text_model=None,
        )
        assert s.is_dual_model is False

    def test_is_dual_model_false_when_only_text_set(self):
        s = _make_dual_settings(
            llm_vision_model=None,
            llm_text_model="openai/gpt-5-mini",
        )
        assert s.is_dual_model is False

    def test_is_dual_model_false_when_neither_set(self):
        s = _make_settings()
        assert s.is_dual_model is False

    def test_single_model_unchanged_when_not_dual(self):
        s = _make_settings()
        assert s.llm_model == "openai/gpt-4"
        assert s.is_dual_model is False


class TestDualModelHistoricalScreenshots:
    @pytest.mark.asyncio
    async def test_historical_screenshots_sent_only_to_vision_model(
        self, dual_evaluator: LLMEvaluator, tmp_path
    ):
        hist_screenshot = tmp_path / "prev.png"
        hist_screenshot.write_bytes(b"prev-png-data")

        ctx = HistoricalContext(
            previous_findings_summary="1 warning",
            previous_health_score=85.0,
            previous_scanned_at=NOW,
            screenshot_path=str(hist_screenshot),
        )
        vision_payload = json.dumps(_make_findings_json(categories=VISION_CATEGORIES))
        text_payload = json.dumps(_make_findings_json(categories=TEXT_CATEGORIES))
        vision_resp = _mock_response(vision_payload, model="google/gemini-2.5-flash")
        text_resp = _mock_response(text_payload, model="openai/gpt-5-mini")

        with patch("qa_bot.services.llm_evaluator.openrouter.OpenRouter") as MockOR:
            call_count = 0

            async def send_side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return vision_resp if call_count == 1 else text_resp

            mock_client = AsyncMock()
            mock_client.chat.send_async = AsyncMock(side_effect=send_side_effect)
            MockOR.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockOR.return_value.__aexit__ = AsyncMock(return_value=False)

            with patch("qa_bot.services.llm_evaluator.datetime") as mock_dt:
                mock_dt.now.return_value = NOW
                mock_dt.UTC = UTC

                with patch(
                    "qa_bot.services.llm_evaluator._resize_screenshot",
                    side_effect=lambda b, w: b,
                ):
                    await dual_evaluator.evaluate(
                        _make_snapshot(),
                        _make_preprocessed(),
                        [],
                        historical_contexts=[ctx],
                    )

        assert mock_client.chat.send_async.call_count == 2

        vision_call = mock_client.chat.send_async.call_args_list[0]
        vision_messages = vision_call.kwargs["messages"]
        vision_images = [
            p
            for p in vision_messages[1].content
            if hasattr(p, "type") and p.type == "image_url"
        ]
        assert len(vision_images) == 2

        text_call = mock_client.chat.send_async.call_args_list[1]
        text_messages = text_call.kwargs["messages"]
        text_images = [
            p
            for p in text_messages[1].content
            if hasattr(p, "type") and p.type == "image_url"
        ]
        assert len(text_images) == 0
