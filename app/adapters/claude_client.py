"""
Claude API Client for AI Enhancement Layer.
Provides async interface to Claude for text cleaning and classification.

DESIGN PRINCIPLES:
- Never hallucinate
- Never infer missing facts
- Never guess authors, brands, dates
- Only return values verifiable against input
- Return UNKNOWN if unsure
"""
import os
from typing import Optional
import anthropic
from app.utils.logger import LayerLogger


# System prompt enforcing strict non-hallucination
SYSTEM_PROMPT = """You are a strict data-cleaning and classification assistant for a structured data generation system.

Your role is NOT to invent or infer information.

You may ONLY:
• Clean noisy strings
• Normalize existing values
• Classify content based on visible text
• Return UNKNOWN if uncertain

ABSOLUTE RULES:
• Never guess missing information
• Never fabricate authors, brands, dates, ratings, reviews
• Never include content not explicitly present in the input
• Never use external knowledge
• Output MUST be deterministic

If the input does not clearly contain the answer, return EXACTLY:
UNKNOWN"""


class ClaudeClient:
    """
    Claude API client for AI enhancement operations.
    
    All operations enforce strict anti-hallucination rules.
    Temperature=0 for deterministic output.
    """
    
    # Model selection
    MODEL_FAST = "claude-3-5-haiku-20241022"  # For simple cleaning tasks
    MODEL_QUALITY = "claude-sonnet-4-20250514"  # For complex tasks
    
    # Allowed categories for article classification
    ALLOWED_CATEGORIES = [
        "Technology", "Science", "Business", "Health", "Sports",
        "Entertainment", "Politics", "Lifestyle", "Travel", "Food"
    ]
    
    def __init__(self):
        self.logger = LayerLogger("claude_client")
        api_key = os.getenv("CLAUDE_API_KEY")
        
        if not api_key:
            self.logger.log_error("CLAUDE_API_KEY not found in environment")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=api_key)
            self.logger.log_action("init", "completed", model=self.MODEL_FAST)
    
    def is_available(self) -> bool:
        """Check if Claude client is properly configured."""
        return self.client is not None
    
    async def clean_author_name(self, raw_byline: str) -> Optional[str]:
        """
        Extract clean author name from noisy byline text.
        
        SAFE: Only extracts names that exist verbatim in input.
        NEVER guesses or fabricates names.
        """
        if not self.client or not raw_byline:
            return None
        
        try:
            self.logger.log_action("clean_author_name", "started", input_length=len(raw_byline))
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=50,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Extract ONLY the author's full name from the text below.

Rules:
• Return ONLY the name
• No titles, roles, dates, punctuation
• The name MUST appear verbatim in the input
• If multiple names appear, return the PRIMARY author
• If no clear personal name is present, return UNKNOWN

Text:
{raw_byline}

Name:"""
                }]
            )
            
            result = response.content[0].text.strip()
            
            # VERIFICATION: result must be substring of original (anti-hallucination)
            if result and result != "UNKNOWN" and result.lower() in raw_byline.lower():
                self.logger.log_action(
                    "clean_author_name", 
                    "success",
                    input=raw_byline[:50],
                    output=result,
                    tokens=response.usage.input_tokens + response.usage.output_tokens
                )
                return result
            else:
                self.logger.log_action(
                    "clean_author_name",
                    "rejected",
                    reason="not_substring" if result != "UNKNOWN" else "unknown_returned",
                    input=raw_byline[:50],
                    output=result
                )
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def extract_author_from_body(self, body_text: str) -> Optional[str]:
        """
        Extract author name from article body text when not found via standard signals.
        VALIDATED: Output must exist verbatim in input text.
        """
        if not self.client or not body_text or len(body_text) < 100:
            return None
        
        try:
            self.logger.log_action("extract_author", "started", body_length=len(body_text))
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=50,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Find the author's name in this article text.

Rules:
• Return ONLY the person's full name
• The name MUST appear exactly in the text
• No titles (VP, Dr, Editor)
• No company names
• If no author found, return UNKNOWN

Text:
{body_text[:1500]}

Author:"""
                }]
            )
            
            result = response.content[0].text.strip()
            
            # VALIDATION: Must be substring of body text
            if result and result != "UNKNOWN" and result.lower() in body_text.lower():
                self.logger.log_action(
                    "extract_author",
                    "success",
                    author=result,
                    tokens=response.usage.input_tokens + response.usage.output_tokens
                )
                return result
            else:
                self.logger.log_action(
                    "extract_author",
                    "rejected",
                    reason="not_in_text" if result != "UNKNOWN" else "unknown_returned",
                    output=result
                )
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    # =========================================================================
    # NEW AI ENHANCEMENTS
    # =========================================================================
    
    # Allowed content types for page classification
    ALLOWED_CONTENT_TYPES = [
        "article", "blog_post", "news_article",
        "product", "service",
        "recipe", "how_to",
        "faq", "event", "video",
        "local_business", "about", "contact",
        "home", "collection", "webpage"
    ]
    
    async def classify_content_type(self, body_text: str, url: str = "") -> Optional[str]:
        """Classify page content type using AI. VALIDATED against enum."""
        if not self.client or not body_text or len(body_text) < 100:
            return None
        
        try:
            self.logger.log_action("classify_content_type", "started", url=url[:50] if url else None)
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=20,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Classify this web page. Return ONLY the type name. No explanation.

TYPES:
article - blog, opinion, guide, tutorial
news_article - journalism, press release, news
product - e-commerce with price/buy button
service - business/professional offering
recipe - cooking instructions with ingredients
how_to - step-by-step instructions
faq - Q&A pairs
event - scheduled event with date/location
video - primarily video content
local_business - physical business location
about - company/brand info
contact - contact page
home - homepage
collection - listing/category page
webpage - fallback

URL: {url[:80] if url else ''}
Content: {body_text[:1200]}

Type:"""
                }]
            )
            
            result = response.content[0].text.strip().split('\n')[0].lower()
            
            if result in self.ALLOWED_CONTENT_TYPES:
                self.logger.log_action("classify_content_type", "success", 
                    content_type=result, tokens=response.usage.input_tokens + response.usage.output_tokens)
                return result
            else:
                self.logger.log_action("classify_content_type", "rejected", reason="not_in_list", output=result)
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def extract_published_date(self, body_text: str) -> Optional[str]:
        """Extract published date from body. Returns ISO format YYYY-MM-DD."""
        if not self.client or not body_text or len(body_text) < 100:
            return None
        
        try:
            self.logger.log_action("extract_date", "started")
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=30,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Find the publication date. Return ONLY in format: YYYY-MM-DD
If no date found, return UNKNOWN.

Text: {body_text[:1200]}

Date:"""
                }]
            )
            
            result = response.content[0].text.strip()
            import re
            if result != "UNKNOWN" and re.match(r'^\d{4}-\d{2}-\d{2}', result):
                self.logger.log_action("extract_date", "success", date=result)
                return result
            else:
                self.logger.log_action("extract_date", "rejected", output=result)
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def extract_publisher(self, body_text: str, url: str = "") -> Optional[str]:
        """Extract publisher/organization. VALIDATED: must exist in text or URL."""
        if not self.client or not body_text or len(body_text) < 100:
            return None
        
        try:
            self.logger.log_action("extract_publisher", "started")
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=50,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Find the publisher or organization name. Return ONLY the name.
If not found, return UNKNOWN.

URL: {url[:100] if url else ''}
Text: {body_text[:800]}

Publisher:"""
                }]
            )
            
            result = response.content[0].text.strip()
            combined = (body_text + " " + url).lower()
            if result != "UNKNOWN" and result.lower() in combined:
                self.logger.log_action("extract_publisher", "success", publisher=result)
                return result
            else:
                self.logger.log_action("extract_publisher", "rejected", output=result)
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def extract_keywords(self, body_text: str, max_keywords: int = 5) -> Optional[list]:
        """Extract top keywords from content. VALIDATED: must exist in text."""
        if not self.client or not body_text or len(body_text) < 100:
            return None
        
        try:
            self.logger.log_action("extract_keywords", "started")
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=50,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Extract {max_keywords} key topics from this content.
Return ONLY comma-separated keywords. No explanation.

Text: {body_text[:1500]}

Keywords:"""
                }]
            )
            
            result = response.content[0].text.strip()
            keywords = [k.strip().lower() for k in result.split(',') if k.strip()]
            
            # Validate: keywords must exist in body
            valid_keywords = [k for k in keywords if k in body_text.lower()]
            
            if valid_keywords:
                self.logger.log_action("extract_keywords", "success", keywords=valid_keywords)
                return valid_keywords[:max_keywords]
            else:
                self.logger.log_action("extract_keywords", "rejected", reason="no_valid_keywords")
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def detect_language(self, body_text: str) -> Optional[str]:
        """Detect content language. Returns ISO language code (en, es, fr, etc.)."""
        if not self.client or not body_text or len(body_text) < 50:
            return None
        
        VALID_LANGUAGES = ["en", "es", "fr", "de", "it", "pt", "ru", "zh", "ja", "ko", "ar", "hi", "nl", "pl", "tr", "vi", "th", "sv", "da", "no", "fi"]
        
        try:
            self.logger.log_action("detect_language", "started")
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=10,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""What language is this text? Return ONLY the 2-letter ISO code (en, es, fr, etc.)

Text: {body_text[:500]}

Language:"""
                }]
            )
            
            result = response.content[0].text.strip().lower()[:2]
            
            if result in VALID_LANGUAGES:
                self.logger.log_action("detect_language", "success", language=result)
                return result
            else:
                self.logger.log_action("detect_language", "rejected", output=result)
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def classify_article_section(self, content_excerpt: str) -> Optional[str]:
        """
        Classify article into a category from controlled enum.
        
        SAFE: Only returns values from ALLOWED_CATEGORIES.
        NEVER invents categories.
        """
        if not self.client or not content_excerpt:
            return None
        
        try:
            self.logger.log_action("classify_section", "started", content_length=len(content_excerpt))
            
            categories_list = "\n".join(self.ALLOWED_CATEGORIES)
            
            response = self.client.messages.create(
                model=self.MODEL_FAST,
                max_tokens=20,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Classify this article into EXACTLY ONE category from the list below.

Allowed categories:
{categories_list}

Rules:
• Choose ONLY from the list
• Base decision ONLY on the provided text
• If classification is ambiguous, return UNKNOWN
• Return ONLY the category name

Article text:
{content_excerpt[:1000]}

Category:"""
                }]
            )
            
            result = response.content[0].text.strip()
            
            # VERIFICATION: must be in allowed list
            if result in self.ALLOWED_CATEGORIES:
                self.logger.log_action(
                    "classify_section",
                    "success",
                    category=result,
                    tokens=response.usage.input_tokens + response.usage.output_tokens
                )
                return result
            else:
                self.logger.log_action(
                    "classify_section",
                    "rejected",
                    reason="not_in_allowed_list",
                    output=result
                )
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
    
    async def generate_description(self, body_text: str, max_length: int = 160) -> Optional[str]:
        """
        Generate meta description from article body.
        
        TRIGGER: Only when description missing or < 50 chars.
        SAFE: Uses only information from the provided text.
        NEVER adds promotional language or external facts.
        """
        if not self.client or not body_text or len(body_text) < 100:
            return None
        
        try:
            self.logger.log_action("generate_description", "started", body_length=len(body_text))
            
            response = self.client.messages.create(
                model=self.MODEL_QUALITY,  # Use Sonnet 4 for better summarization
                max_tokens=100,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"""Write ONE factual sentence summarizing the article.

Rules:
• Max {max_length} characters
• Neutral tone
• No marketing language
• No opinions
• No added facts
• Use ONLY information from the text
• If a clear summary cannot be written, return UNKNOWN

Article text:
{body_text[:2000]}

Summary:"""
                }]
            )
            
            result = response.content[0].text.strip()
            
            # Handle UNKNOWN
            if result == "UNKNOWN":
                self.logger.log_action(
                    "generate_description",
                    "rejected",
                    reason="unknown_returned"
                )
                return None
            
            # Truncate if too long
            if len(result) > max_length:
                result = result[:max_length-3] + "..."
            
            # VERIFICATION: length must be reasonable
            if result and 50 <= len(result) <= max_length:
                self.logger.log_action(
                    "generate_description",
                    "success",
                    length=len(result),
                    tokens=response.usage.input_tokens + response.usage.output_tokens
                )
                return result
            else:
                self.logger.log_action(
                    "generate_description",
                    "rejected",
                    reason="invalid_length",
                    length=len(result) if result else 0
                )
                return None
                
        except Exception as e:
            self.logger.log_error(f"Claude API error: {str(e)}", error_type="api_error")
            return None
