"""
AI Enhancement Layer for Structured Data Generation.
Provides optional AI-powered cleaning and classification for extracted content.

COMPREHENSIVE LOGGING:
- Every operation logged with input/output
- All conditions and decisions logged
- Success/failure with reasons
- Token usage tracked
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from app.models.content import NormalizedContent
from app.adapters.claude_client import ClaudeClient
from app.utils.logger import LayerLogger


@dataclass
class EnhancementResult:
    """Result of an AI enhancement operation."""
    field: str
    original: Optional[str]
    enhanced: Optional[str]
    enhancement_type: str
    success: bool
    reason: Optional[str] = None


@dataclass
class AIEnhancementReport:
    """Report of all AI enhancements applied to content."""
    ai_enhanced: bool = False
    enhancements: List[EnhancementResult] = field(default_factory=list)
    
    def add_enhancement(self, result: EnhancementResult):
        """Add an enhancement result to the report."""
        self.enhancements.append(result)
        if result.success:
            self.ai_enhanced = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for API response."""
        return {
            "ai_enhanced": self.ai_enhanced,
            "enhancements": [
                {
                    "field": e.field,
                    "original": e.original,
                    "enhanced": e.enhanced,
                    "type": e.enhancement_type,
                    "success": e.success,
                    "reason": e.reason
                }
                for e in self.enhancements
            ]
        }


class AIEnhancementLayer:
    """
    AI Enhancement Layer for structured data extraction.
    
    Principles:
    - All enhancements are optional (opt-in)
    - AI cannot fabricate data, only clean/classify
    - All outputs are verified against source
    - Failures fall back to original values
    - EVERY operation is logged
    """
    
    def __init__(self):
        self.logger = LayerLogger("ai_enhancement")
        self.claude = ClaudeClient()
        self.logger.log_action(
            "init",
            "completed",
            claude_available=self.claude.is_available()
        )
    
    def is_available(self) -> bool:
        """Check if AI enhancement is available."""
        return self.claude.is_available()
    
    async def enhance_content(
        self, 
        content: NormalizedContent,
        body_text: Optional[str] = None
    ) -> tuple[NormalizedContent, AIEnhancementReport]:
        """
        Apply AI enhancements to normalized content.
        """
        report = AIEnhancementReport()
        
        # Log entry point
        self.logger.log_action(
            "enhance_content",
            "started",
            url=content.url,
            content_type=content.content_type.value,
            has_author=(content.author is not None),
            has_article_section=(content.article_section is not None),
            has_description=(content.description is not None),
            description_length=len(content.description) if content.description else 0,
            body_length=len(body_text) if body_text else 0
        )
        
        if not self.is_available():
            self.logger.log_action(
                "enhance_content",
                "aborted",
                reason="claude_not_available"
            )
            return content, report
        
        # =====================================================================
        # Enhancement 1: Author name cleaning
        # =====================================================================
        if content.author:
            self.logger.log_action(
                "author_enhancement",
                "evaluating",
                original_author=content.author[:50] if content.author else None,
                author_length=len(content.author) if content.author else 0
            )
            
            enhanced_author = await self._enhance_author(content.author, report)
            
            if enhanced_author:
                self.logger.log_action(
                    "author_enhancement",
                    "applied",
                    original=content.author[:50],
                    enhanced=enhanced_author
                )
                content.author = enhanced_author
            else:
                self.logger.log_action(
                    "author_enhancement",
                    "skipped",
                    reason="no_enhancement_needed_or_failed"
                )
        else:
            # No author found - try AI extraction from body text
            if content.content_type.value in ["article", "blog_post"] and body_text:
                self.logger.log_action(
                    "author_extraction",
                    "attempting",
                    reason="no_author_in_html"
                )
                extracted_author = await self._extract_author(body_text, report)
                if extracted_author:
                    self.logger.log_action(
                        "author_extraction",
                        "applied",
                        author=extracted_author
                    )
                    content.author = extracted_author
                else:
                    self.logger.log_action(
                        "author_extraction",
                        "failed",
                        reason="not_found_in_body"
                    )
            else:
                self.logger.log_action(
                    "author_enhancement",
                    "skipped",
                    reason="no_author_and_not_article"
                )
        
        # =====================================================================
        # Enhancement 2: Article section classification
        # =====================================================================
        content_type_value = content.content_type.value
        should_classify = content_type_value in ["article", "blog_post"] and not content.article_section
        
        self.logger.log_action(
            "section_classification",
            "evaluating",
            content_type=content_type_value,
            has_article_section=(content.article_section is not None),
            should_classify=should_classify
        )
        
        if should_classify:
            section = await self._enhance_section(body_text or content.body, report)
            
            if section:
                self.logger.log_action(
                    "section_classification",
                    "applied",
                    section=section
                )
                content.article_section = section
            else:
                self.logger.log_action(
                    "section_classification",
                    "failed",
                    reason="classification_returned_none"
                )
        
        # =====================================================================
        # Enhancement 3: Description fallback
        # =====================================================================
        desc_length = len(content.description) if content.description else 0
        needs_description = not content.description or desc_length < 50
        
        self.logger.log_action(
            "description_fallback",
            "evaluating",
            current_description=content.description[:50] if content.description else None,
            description_length=desc_length,
            needs_fallback=needs_description
        )
        
        if needs_description:
            description = await self._enhance_description(
                body_text or content.body, 
                content.description,
                report
            )
            
            if description:
                self.logger.log_action(
                    "description_fallback",
                    "applied",
                    original_length=desc_length,
                    new_description=description[:80],
                    new_length=len(description)
                )
                content.description = description
            else:
                self.logger.log_action(
                    "description_fallback",
                    "failed",
                    reason="generation_returned_none"
                )
        
        # =====================================================================
        # Final summary
        # =====================================================================
        successful = [e for e in report.enhancements if e.success]
        failed = [e for e in report.enhancements if not e.success]
        
        self.logger.log_action(
            "enhance_content",
            "completed",
            url=content.url,
            total_enhancements=len(report.enhancements),
            successful_count=len(successful),
            failed_count=len(failed),
            successful_fields=[e.field for e in successful],
            failed_fields=[e.field for e in failed],
            ai_enhanced=report.ai_enhanced
        )
        
        return content, report
    
    async def _enhance_author(
        self, 
        raw_author: str, 
        report: AIEnhancementReport
    ) -> Optional[str]:
        """Clean author name using AI."""
        
        # Skip if already clean (simple name pattern)
        is_clean = (
            raw_author and 
            len(raw_author.split()) <= 3 and 
            '|' not in raw_author and 
            ',' not in raw_author and
            ' by ' not in raw_author.lower() and
            not raw_author.lower().startswith('by ')
        )
        
        if is_clean:
            self.logger.log_action(
                "author_cleaning",
                "skipped",
                reason="already_clean",
                author=raw_author
            )
            return None  # Already clean, no enhancement needed
        
        self.logger.log_action(
            "author_cleaning",
            "calling_claude",
            input_length=len(raw_author),
            input_preview=raw_author[:50]
        )
        
        enhanced = await self.claude.clean_author_name(raw_author)
        
        result = EnhancementResult(
            field="author",
            original=raw_author,
            enhanced=enhanced,
            enhancement_type="name_cleaning",
            success=enhanced is not None and enhanced != raw_author,
            reason=None if enhanced else "cleaning_failed"
        )
        report.add_enhancement(result)
        
        self.logger.log_action(
            "author_cleaning",
            "result",
            success=result.success,
            original=raw_author[:50],
            enhanced=enhanced,
            reason=result.reason
        )
        
        return enhanced
    
    async def _extract_author(
        self, 
        body_text: str, 
        report: AIEnhancementReport
    ) -> Optional[str]:
        """Extract author from body text using AI when not found via signals."""
        
        author = await self.claude.extract_author_from_body(body_text)
        
        result = EnhancementResult(
            field="author",
            original=None,
            enhanced=author,
            enhancement_type="extraction",
            success=author is not None,
            reason=None if author else "extraction_failed"
        )
        report.add_enhancement(result)
        
        return author
    
    async def _enhance_section(
        self, 
        body_text: Optional[str], 
        report: AIEnhancementReport
    ) -> Optional[str]:
        """Classify article section using AI."""
        
        if not body_text or len(body_text) < 200:
            self.logger.log_action(
                "section_classification",
                "skipped",
                reason="body_too_short",
                body_length=len(body_text) if body_text else 0
            )
            return None
        
        self.logger.log_action(
            "section_classification",
            "calling_claude",
            body_length=len(body_text),
            body_preview=body_text[:100]
        )
        
        section = await self.claude.classify_article_section(body_text[:1500])
        
        result = EnhancementResult(
            field="articleSection",
            original=None,
            enhanced=section,
            enhancement_type="classification",
            success=section is not None,
            reason=None if section else "classification_failed"
        )
        report.add_enhancement(result)
        
        self.logger.log_action(
            "section_classification",
            "result",
            success=result.success,
            section=section,
            reason=result.reason
        )
        
        return section
    
    async def _enhance_description(
        self, 
        body_text: Optional[str],
        current_description: Optional[str],
        report: AIEnhancementReport
    ) -> Optional[str]:
        """Generate description fallback using AI."""
        
        if not body_text or len(body_text) < 200:
            self.logger.log_action(
                "description_generation",
                "skipped",
                reason="body_too_short",
                body_length=len(body_text) if body_text else 0
            )
            return None
        
        self.logger.log_action(
            "description_generation",
            "calling_claude",
            body_length=len(body_text),
            current_description_length=len(current_description) if current_description else 0
        )
        
        description = await self.claude.generate_description(body_text)
        
        result = EnhancementResult(
            field="description",
            original=current_description,
            enhanced=description,
            enhancement_type="generation",
            success=description is not None,
            reason=None if description else "generation_failed"
        )
        report.add_enhancement(result)
        
        self.logger.log_action(
            "description_generation",
            "result",
            success=result.success,
            description_length=len(description) if description else 0,
            description_preview=description[:80] if description else None,
            reason=result.reason
        )
        
        return description
