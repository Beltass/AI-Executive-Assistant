"""Innovation/Ideas generation advisor — İnovasyon Laboratuvarı.

Analyzes existing reports and sector intelligence to proactively identify gaps,
opportunities, and actionable improvement suggestions.

Behavior:
    - Scans recent briefings and sector trends for patterns and incomplete tasks
    - Cross-references with sector developments to spot market opportunities
    - Generates structured suggestions for projects, features, and optimizations
    - Rates each idea by effort (1-5) and potential impact (1-5)
    - Returns structured JSON with idea categories and next steps

LLM-backed: produces a Turkish JSON briefing with actionable innovation ideas.
With no LLM provider key the advisor is ``skipped``.

Configuration (via environment):
    RECENT_REPORTS_DIR    Directory containing recent briefing JSON files
                         (defaults to ``frontend/reports``).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ._llm_base import RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sen bir inovasyon ve stratejik fırsatlar uzmanısın. Türkçe konuşuyorsun. "
    "Görevin, mevcut raporlar ve sektör gelişmelerini analiz ederek, "
    "yapılmamış işleri, eksiklikleri ve market fırsatlarını belirlemek ve "
    "bunları somut, uygulanabilir iyileştirme önerileri olarak sunmak. "
    "Öneriler aşağıdaki kategorilerde olabilir: process (iş süreci iyileştirme), "
    "feature (yeni özellik/araç), project (yeni proje), learning (eğitim ve "
    "gelişim). Her öneride çabayı (1-5), potansiyel etkiyi (1-5) ve somut "
    "sonraki adımları değerlendir. Stratejik, pratik ve İş değeri yüksek olsun."
)

REPORTS_DIR_ENV = "RECENT_REPORTS_DIR"
DEFAULT_REPORTS_DIR = "frontend/reports"


@dataclass
class IdeaItem:
    """One generated idea."""

    title: str
    category: str  # process|feature|project|learning
    description: str
    rationale: str
    effort: int  # 1-5
    impact: int  # 1-5
    next_steps: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "rationale": self.rationale,
            "effort": self.effort,
            "impact": self.impact,
            "next_steps": self.next_steps,
        }


class InnovationLabAdvisor(Advisor):
    key = "innovation_lab"
    title = "İnovasyon Laboratuvarı"

    # This advisor analyzes internal reports, so content is private.
    private = True

    # May have genuinely new ideas between runs if reports change.
    incremental_source = False

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )

        try:
            text = llm.generate_text(self.system_prompt, self._user_prompt())
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.ok(self._format_response(text))

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not llm.is_configured():
            return None
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=self.system_prompt,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        return self.ok(self._format_response(text))

    # -- properties -------------------------------------------------------
    @property
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    # -- helpers ---------------------------------------------------------
    def _user_prompt(self) -> str:
        recent_findings = self._gather_recent_findings()
        sector_context = self._gather_sector_context()

        user_prompt = (
            "Aşağıda son brifingler ve sektör gelişmeleri verilmiştir. "
            "Buna dayanarak, gelecek 1-3 ay içinde yapılabilecek "
            "5-8 somut İnovasyon önerisi yap:\n\n"
        )

        if recent_findings:
            user_prompt += f"SON BRIFING BULGULARI:\n{recent_findings}\n\n"
        else:
            user_prompt += (
                "SON BRIFING BULGULARI: son raporlar erişilemedi; "
                "genel bilginize dayanarak öner.\n\n"
            )

        if sector_context:
            user_prompt += f"SEKTÖR BAĞLAMI:\n{sector_context}\n\n"

        user_prompt += (
            "ÇIKTI KURALLARI:\n"
            "Yanıtını Türkçe olarak aşağıdaki JSON yapısında ver "
            "(Markdown kod bloğu YOKSAY, sadece JSON verisi):\n"
            "```json\n"
            "{\n"
            '  "generated_at": "ISO 8601 timestamp",\n'
            '  "ideas": [\n'
            "    {\n"
            '      "title": "Türkçe başlık",\n'
            '      "category": "process|feature|project|learning",\n'
            '      "description": "2-3 cümlelik Türkçe açıklama",\n'
            '      "rationale": "Neden bu önem taşıyor ve hangi problemi çözüyor",\n'
            '      "effort": 1 - 5 (1=minimal, 5=yüksek),\n'
            '      "impact": 1 - 5 (1=minimal, 5=transformatif),\n'
            '      "next_steps": ["İlk adım", "İkinci adım", "Başarı ölçütü"]\n'
            "    },\n"
            "    ...\n"
            "  ],\n"
            '  "summary": "Genel insight: neden bu öneriler stratejik önem taşıyor"\n'
            "}\n"
            "```\n\n"
            "TAVSIYELER:\n"
            "- Her fikir SPESIFIK ve UYGULANABILIR olsun.\n"
            "- Çalışma ve etki puanlaması tutarlı olsun "
            "(örn. high-impact, low-effort çiçekler önce).\n"
            "- Next steps 2-4 somut, haftalık faaliyet olsun.\n"
            "- Kategorileri dengeli seç (tümü project olmasın).\n"
            "- Gerekirse mevcut ekip kapasitesi ve bütçe varsayımlarını açıkla."
        )

        return user_prompt

    def _gather_recent_findings(self) -> str:
        """Read the last 3 days of briefing files and extract key findings."""
        try:
            reports_dir = (setting(REPORTS_DIR_ENV) or DEFAULT_REPORTS_DIR).strip()
            if not os.path.isdir(reports_dir):
                return ""

            findings = []
            # List date directories sorted by name (descending for recent first)
            entries = sorted(
                [d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d))],
                reverse=True,
            )[:3]  # Last 3 days

            for day_dir in entries:
                day_path = os.path.join(reports_dir, day_dir)
                for advisor_file in os.listdir(day_path):
                    if not advisor_file.endswith(".json"):
                        continue
                    try:
                        with open(os.path.join(day_path, advisor_file), "r", encoding="utf-8") as f:
                            data = json.load(f)
                            title = data.get("title", "").strip()
                            headline = data.get("headline", "").strip()
                            if title and headline:
                                findings.append(f"- {title}: {headline}")
                    except Exception as e:
                        logger.debug(f"Failed to read {advisor_file}: {e}")
                        continue

            return "\n".join(findings[:15]) if findings else ""

        except Exception as e:
            logger.debug(f"Error gathering recent findings: {e}")
            return ""

    def _gather_sector_context(self) -> str:
        """Extract sector intelligence from recent sector_intel briefing if available."""
        try:
            reports_dir = (setting(REPORTS_DIR_ENV) or DEFAULT_REPORTS_DIR).strip()
            if not os.path.isdir(reports_dir):
                return ""

            # Look for sector_intel.json in the most recent date
            entries = sorted(
                [d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d))],
                reverse=True,
            )[:1]

            if entries:
                sector_file = os.path.join(reports_dir, entries[0], "sector_intel.json")
                if os.path.exists(sector_file):
                    with open(sector_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        text = data.get("text", "").strip()
                        # Extract first 500 chars to avoid overwhelming the model
                        return text[:500] + "..." if len(text) > 500 else text

            return ""

        except Exception as e:
            logger.debug(f"Error gathering sector context: {e}")
            return ""

    def _format_response(self, llm_output: str) -> str:
        """Parse LLM response and format as structured output."""
        try:
            # Try to extract JSON from the response
            # LLM might wrap it in markdown code blocks
            text = llm_output.strip()
            if text.startswith("```"):
                # Extract from code block
                lines = text.split("\n")
                start_idx = None
                for i, line in enumerate(lines):
                    if line.strip().startswith("{"):
                        start_idx = i
                        break
                if start_idx is not None:
                    end_idx = None
                    for i in range(len(lines) - 1, start_idx, -1):
                        if lines[i].strip().startswith("}"):
                            end_idx = i
                            break
                    if end_idx is not None:
                        text = "\n".join(lines[start_idx : end_idx + 1])

            # Parse and validate JSON
            data = json.loads(text)

            # Ensure it has the expected structure
            if "ideas" not in data:
                data["ideas"] = []
            if "generated_at" not in data:
                data["generated_at"] = datetime.utcnow().isoformat() + "Z"
            if "summary" not in data:
                data["summary"] = "İnovasyon önerileri oluşturuldu."

            # Validate and clean idea entries
            validated_ideas = []
            for idea in data.get("ideas", []):
                if isinstance(idea, dict):
                    validated_idea = {
                        "title": idea.get("title", ""),
                        "category": idea.get("category", "project"),
                        "description": idea.get("description", ""),
                        "rationale": idea.get("rationale", ""),
                        "effort": max(1, min(5, int(idea.get("effort", 3)))),
                        "impact": max(1, min(5, int(idea.get("impact", 3)))),
                        "next_steps": idea.get("next_steps", [])
                        if isinstance(idea.get("next_steps"), list)
                        else [],
                    }
                    if validated_idea["title"]:  # Only include if has title
                        validated_ideas.append(validated_idea)

            data["ideas"] = validated_ideas
            return json.dumps(data, ensure_ascii=False, indent=2)

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            # Return a minimal valid structure with the raw text as a note
            fallback = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "ideas": [
                    {
                        "title": "İnovasyon önerileri işleniyor",
                        "category": "project",
                        "description": llm_output[:200],
                        "rationale": "Model çıktısı işlendi",
                        "effort": 3,
                        "impact": 3,
                        "next_steps": ["Ham çıktıyı inceleyiniz"],
                    }
                ],
                "summary": "JSON ayrıştırma başarısız; ham çıktı kaydedildi.",
            }
            return json.dumps(fallback, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error formatting response: {e}")
            fallback = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "ideas": [],
                "summary": f"Hata oluştu: {str(e)}",
            }
            return json.dumps(fallback, ensure_ascii=False, indent=2)
