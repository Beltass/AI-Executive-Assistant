"""Tests for Gemini LLM service."""

import pytest
from app.services.gemini_service import GeminiService


@pytest.fixture
def gemini_service():
    """Create GeminiService instance."""
    return GeminiService()


class TestGeminiContentGeneration:
    """Tests for content generation."""

    @pytest.mark.asyncio
    async def test_generate_variations_returns_dict(self, gemini_service):
        """Test that generate_variations returns a dictionary."""
        result = await gemini_service.generate_content_variations(
            topic="AI in business",
            platform="linkedin",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_variations_has_main_content(self, gemini_service):
        """Test that result contains main_content."""
        result = await gemini_service.generate_content_variations(
            topic="AI in business",
            platform="linkedin",
        )
        assert "main_content" in result

    @pytest.mark.asyncio
    async def test_generate_variations_has_variations(self, gemini_service):
        """Test that result contains variations."""
        result = await gemini_service.generate_content_variations(
            topic="AI in business",
            platform="linkedin",
        )
        assert "variations" in result

    @pytest.mark.asyncio
    async def test_generate_with_tone(self, gemini_service):
        """Test content generation with tone parameter."""
        result = await gemini_service.generate_content_variations(
            topic="AI in business",
            platform="linkedin",
            tone="professional",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_with_language(self, gemini_service):
        """Test content generation with language parameter."""
        result = await gemini_service.generate_content_variations(
            topic="AI in business",
            platform="linkedin",
            language="tr",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_with_additional_context(self, gemini_service):
        """Test content generation with additional context."""
        result = await gemini_service.generate_content_variations(
            topic="AI in business",
            platform="linkedin",
            additional_context="Target audience: executives",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_for_different_platforms(self, gemini_service):
        """Test content generation for different platforms."""
        platforms = ["linkedin", "twitter", "instagram", "email"]
        for platform in platforms:
            result = await gemini_service.generate_content_variations(
                topic="AI in business",
                platform=platform,
            )
            assert isinstance(result, dict)


class TestGeminiOptimalPostingTime:
    """Tests for optimal posting time calculation."""

    @pytest.mark.asyncio
    async def test_optimal_posting_time_returns_dict(self, gemini_service):
        """Test that optimal posting time returns dictionary."""
        result = await gemini_service.generate_optimal_posting_time(
            platform="linkedin",
            user_timezone="UTC",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_optimal_posting_time_has_time(self, gemini_service):
        """Test that result contains optimal_time."""
        result = await gemini_service.generate_optimal_posting_time(
            platform="linkedin",
            user_timezone="UTC",
        )
        assert "optimal_time" in result

    @pytest.mark.asyncio
    async def test_optimal_posting_time_has_confidence(self, gemini_service):
        """Test that result contains confidence score."""
        result = await gemini_service.generate_optimal_posting_time(
            platform="linkedin",
            user_timezone="UTC",
        )
        assert "confidence_score" in result

    @pytest.mark.asyncio
    async def test_optimal_time_for_different_platforms(self, gemini_service):
        """Test optimal time for different platforms."""
        platforms = ["linkedin", "twitter", "instagram"]
        for platform in platforms:
            result = await gemini_service.generate_optimal_posting_time(
                platform=platform,
                user_timezone="UTC",
            )
            assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_optimal_time_respects_timezone(self, gemini_service):
        """Test that optimal time respects user timezone."""
        timezones = ["UTC", "EST", "PST", "CET"]
        for tz in timezones:
            result = await gemini_service.generate_optimal_posting_time(
                platform="linkedin",
                user_timezone=tz,
            )
            assert isinstance(result, dict)


class TestGeminiContentFitAnalysis:
    """Tests for content fit analysis."""

    @pytest.mark.asyncio
    async def test_analyze_fit_returns_dict(self, gemini_service):
        """Test that analyze fit returns dictionary."""
        result = await gemini_service.analyze_content_fit(
            content="AI is transforming business",
            industry="Technology",
            audience="Business executives",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_analyze_fit_has_score(self, gemini_service):
        """Test that result contains fit_score."""
        result = await gemini_service.analyze_content_fit(
            content="AI is transforming business",
            industry="Technology",
            audience="Business executives",
        )
        assert "fit_score" in result

    @pytest.mark.asyncio
    async def test_analyze_fit_has_strengths(self, gemini_service):
        """Test that result contains strengths."""
        result = await gemini_service.analyze_content_fit(
            content="AI is transforming business",
            industry="Technology",
            audience="Business executives",
        )
        assert "strengths" in result

    @pytest.mark.asyncio
    async def test_analyze_fit_has_weaknesses(self, gemini_service):
        """Test that result contains weaknesses."""
        result = await gemini_service.analyze_content_fit(
            content="AI is transforming business",
            industry="Technology",
            audience="Business executives",
        )
        assert "weaknesses" in result

    @pytest.mark.asyncio
    async def test_analyze_fit_has_recommendations(self, gemini_service):
        """Test that result contains recommendations."""
        result = await gemini_service.analyze_content_fit(
            content="AI is transforming business",
            industry="Technology",
            audience="Business executives",
        )
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_fit_score_in_valid_range(self, gemini_service):
        """Test that fit score is between 0 and 1."""
        result = await gemini_service.analyze_content_fit(
            content="AI is transforming business",
            industry="Technology",
            audience="Business executives",
        )
        score = result.get("fit_score", 0)
        assert 0 <= score <= 1
