"""Service for Google Gemini LLM integration."""

import json
import logging
from typing import Dict, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class GeminiService:
    """Service for interacting with Google Gemini API."""

    def __init__(self):
        """Initialize Gemini service."""
        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel("gemini-1.5-flash")
            self.genai = genai
        except ImportError:
            logger.warning("google-generativeai not installed, using mock service")
            self.model = None
            self.genai = None

    async def generate_content_variations(
        self,
        topic: str,
        platform: str,
        language: str = "en",
        tone: Optional[str] = None,
        additional_context: Optional[str] = None,
    ) -> Dict[str, any]:
        """
        Generate multiple content variations for a given topic.

        Args:
            topic: The topic to generate content for
            platform: Target platform (linkedin, twitter, etc.)
            language: Language code (en, tr, etc.)
            tone: Tone of content (professional, casual, etc.)
            additional_context: Additional context for generation

        Returns:
            Dictionary with main_content and variations
        """
        if not self.model:
            # Return mock data for testing
            return self._mock_generate_variations(topic, platform)

        try:
            prompt = self._build_generation_prompt(
                topic=topic,
                platform=platform,
                language=language,
                tone=tone,
                additional_context=additional_context,
            )

            response = self.model.generate_content(prompt)
            content_text = response.text

            # Parse JSON response
            result = self._parse_generation_response(content_text)
            return result

        except Exception as e:
            logger.error(f"Error generating content: {e}")
            return self._mock_generate_variations(topic, platform)

    async def generate_optimal_posting_time(
        self, platform: str, user_timezone: str
    ) -> Dict[str, any]:
        """
        Calculate optimal posting time based on platform and user timezone.

        Args:
            platform: Social media platform
            user_timezone: User's timezone

        Returns:
            Dictionary with optimal posting time and confidence score
        """
        if not self.model:
            return self._mock_posting_time(platform)

        try:
            prompt = f"""
Based on platform analytics for {platform}:
- What is the optimal posting time for maximum engagement?
- Consider timezone: {user_timezone}

Return as JSON:
{{
    "optimal_time": "HH:MM",
    "confidence_score": 0.0-1.0,
    "rationale": "explanation"
}}
"""
            response = self.model.generate_content(prompt)
            result = json.loads(response.text)
            return result

        except Exception as e:
            logger.error(f"Error generating optimal posting time: {e}")
            return self._mock_posting_time(platform)

    async def analyze_content_fit(
        self, content: str, industry: str, audience: str
    ) -> Dict[str, any]:
        """
        Analyze how well content fits audience and industry.

        Args:
            content: Content to analyze
            industry: Target industry
            audience: Target audience description

        Returns:
            Dictionary with fit score and recommendations
        """
        if not self.model:
            return self._mock_fit_analysis()

        try:
            prompt = f"""
Analyze this content for fit with the industry and audience:

Content: {content}
Industry: {industry}
Audience: {audience}

Return as JSON:
{{
    "fit_score": 0.0-1.0,
    "strengths": ["strength1", "strength2"],
    "weaknesses": ["weakness1", "weakness2"],
    "recommendations": ["recommendation1"]
}}
"""
            response = self.model.generate_content(prompt)
            result = json.loads(response.text)
            return result

        except Exception as e:
            logger.error(f"Error analyzing content fit: {e}")
            return self._mock_fit_analysis()

    def _build_generation_prompt(
        self,
        topic: str,
        platform: str,
        language: str = "en",
        tone: Optional[str] = None,
        additional_context: Optional[str] = None,
    ) -> str:
        """Build a prompt for content generation."""
        tone_instruction = f" Tone: {tone}." if tone else ""
        context_instruction = (
            f" Additional context: {additional_context}" if additional_context else ""
        )

        prompt = f"""
Generate 5 variations of content for the following:
Topic: {topic}
Platform: {platform}
Language: {language}{tone_instruction}{context_instruction}

For each variation, create:
1. Main content text (optimized for the platform)
2. Tone description
3. Key hooks/engaging elements

Return as JSON:
{{
    "main_content": "primary content for the topic",
    "variations": [
        {{
            "variation_1": {{
                "text": "content text",
                "tone": "tone description",
                "hooks": ["hook1", "hook2"]
            }}
        }},
        ...
    ]
}}
"""
        return prompt

    def _parse_generation_response(self, response_text: str) -> Dict[str, any]:
        """Parse JSON response from Gemini."""
        try:
            # Extract JSON from response
            result = json.loads(response_text)
            return result
        except json.JSONDecodeError:
            # Fallback if JSON parsing fails
            return {
                "main_content": response_text,
                "variations": [],
                "success": False,
            }

    def _mock_generate_variations(self, topic: str, platform: str) -> Dict[str, any]:
        """Generate mock content variations for testing."""
        return {
            "main_content": (
                f"High-quality content about {topic} optimized for {platform}"
            ),
            "variations": [
                {
                    "variation_1": {
                        "text": f"First take on {topic}",
                        "tone": "professional",
                        "hooks": ["engaging", "insightful"],
                    }
                },
                {
                    "variation_2": {
                        "text": f"Second perspective on {topic}",
                        "tone": "casual",
                        "hooks": ["relatable", "actionable"],
                    }
                },
            ],
        }

    def _mock_posting_time(self, platform: str) -> Dict[str, any]:
        """Generate mock posting time."""
        times = {
            "linkedin": "09:00",
            "twitter": "14:00",
            "instagram": "11:00",
            "email": "10:00",
        }
        return {
            "optimal_time": times.get(platform, "10:00"),
            "confidence_score": 0.85,
            "rationale": f"Based on typical engagement patterns for {platform}",
        }

    def _mock_fit_analysis(self) -> Dict[str, any]:
        """Generate mock fit analysis."""
        return {
            "fit_score": 0.87,
            "strengths": [
                "Clear value proposition",
                "Relevant to audience",
                "Actionable",
            ],
            "weaknesses": ["Could be more concise"],
            "recommendations": [
                "Add specific examples",
                "Include call-to-action",
            ],
        }
