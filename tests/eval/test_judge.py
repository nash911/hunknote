"""Tests for LLM-as-judge scoring."""

import json

import pytest

from eval.judge import _call_and_parse


class TestCallAndParse:
    def test_parses_valid_json(self):
        def mock_llm(system, user):
            return '{"score": 0.8, "reasoning": "Good cohesion"}'

        score, reasoning = _call_and_parse(mock_llm, "system", "user")
        assert score == 0.8
        assert reasoning == "Good cohesion"

    def test_parses_markdown_json(self):
        def mock_llm(system, user):
            return '```json\n{"score": 0.9, "reasoning": "Great"}\n```'

        score, reasoning = _call_and_parse(mock_llm, "system", "user")
        assert score == 0.9

    def test_clamps_score(self):
        def mock_llm(system, user):
            return '{"score": 1.5, "reasoning": "Over"}'

        score, _ = _call_and_parse(mock_llm, "system", "user")
        assert score == 1.0

    def test_clamps_negative_score(self):
        def mock_llm(system, user):
            return '{"score": -0.5, "reasoning": "Negative"}'

        score, _ = _call_and_parse(mock_llm, "system", "user")
        assert score == 0.0

    def test_handles_parse_error(self):
        def mock_llm(system, user):
            return "not json at all"

        score, reasoning = _call_and_parse(mock_llm, "system", "user")
        assert score == 0.5  # Default
        assert "Parse error" in reasoning

    def test_handles_exception(self):
        def mock_llm(system, user):
            raise RuntimeError("API error")

        score, reasoning = _call_and_parse(mock_llm, "system", "user")
        assert score == 0.5
        assert "Parse error" in reasoning
