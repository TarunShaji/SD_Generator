"""
HTML Scraper Adapter for the Structured Data Automation Tool.
Used as fallback when REST APIs are unavailable or in HTML-only mode.
"""
import json
import re
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.models.content import (
    NormalizedContent,
    SourceType,
    ContentType,
    ImageData,
    HeadingData,
    FAQItem,
    BreadcrumbItem,
    ProductOffer,
    AggregateRatingData,
    ProductVariant,
)
from app.utils.logger import LayerLogger


class HTMLScraper:
    """
    HTML scraping adapter for content extraction.
    Converts raw HTML into normalized content model.
    """
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.logger = LayerLogger("html_scraper")
    
    async def fetch_and_parse(self, url: str, reason: str = "explicit_mode") -> NormalizedContent:
        """
        Fetch HTML from URL and parse into normalized content.
        
        Args:
            url: The URL to fetch
            reason: Why scraping is being used (for logging)
        
        Returns:
            NormalizedContent model
        """
        self.logger.log_action("fetch_html", "started", url=url, reason=reason)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=self._get_headers())
                response.raise_for_status()
                html = response.text
                
            self.logger.log_action(
                "fetch_html", 
                "completed", 
                url=url,
                status_code=response.status_code,
                content_length=len(html)
            )
            
            return self._parse_html(url, html)
            
        except httpx.HTTPError as e:
            self.logger.log_error(
                f"Failed to fetch URL: {str(e)}",
                error_type="http_error",
                url=url
            )
            raise
    
    def _get_headers(self) -> dict:
        """Get request headers mimicking a browser."""
        return {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
    
    def _parse_html(self, url: str, html: str) -> NormalizedContent:
        """Parse HTML into normalized content model."""
        self.logger.log_action("parse_html", "started", url=url)
        
        soup = BeautifulSoup(html, "lxml")
        
        # Step 1: UNIFIED JSON-LD parsing (parse ALL scripts ONCE)
        jsonld_graph = self._parse_all_jsonld(soup)
        
        # Step 2: Extract product data from multiple sources (using unified JSON-LD)
        script_data = self._extract_script_json_data(soup, jsonld_graph)
        
        # Extract components
        title = self._extract_title(soup)
        description = self._extract_meta_description(soup)
        body = self._extract_body_text(soup)
        headings = self._extract_headings(soup)
        images = self._extract_images(soup, url)
        faq = self._extract_faq(soup)
        
        # Breadcrumbs use unified JSON-LD (no re-parsing)
        breadcrumbs = self._extract_breadcrumbs_unified(soup, url, jsonld_graph)
        
        # Content type detection with article signals (pass body for word count)
        content_type, article_signals = self._detect_content_type(soup, url, headings, faq, body)
        
        # Calculate word count for article detection
        word_count = len(body.split()) if body else 0
        
        # Extract og:image for articles
        og_image = self._extract_og_image(soup, url)
        
        # Calculate confidence score
        confidence = self._calculate_confidence(title, description, body, headings)
        
        # Boost confidence if product data was extracted from script
        if script_data.get("product_offer"):
            confidence = min(confidence + 0.1, 1.0)
        
        content = NormalizedContent(
            url=url,
            title=title,
            description=description,
            body=body,
            headings=headings,
            images=images,
            faq=faq,
            breadcrumbs=breadcrumbs,
            content_type=content_type,
            source_type=SourceType.HTML_SCRAPER,
            confidence_score=confidence,
            author=self._extract_author(soup),
            published_date=self._extract_date(soup, "published"),
            modified_date=self._extract_date(soup, "modified"),
            organization_name=self._extract_organization(soup),
            organization_logo=self._extract_logo(soup, url),
            # Product-specific fields from script JSON extraction
            product_sku=script_data.get("sku"),
            product_mpn=script_data.get("mpn"),
            product_brand=script_data.get("brand"),
            product_offer=script_data.get("product_offer"),
            product_rating=script_data.get("product_rating"),
            product_variants=script_data.get("product_variants", []),
            product_images=script_data.get("product_images", []),
            # Delivery info from DOM extraction
            delivery_info=script_data.get("delivery_text"),
            # Article-specific fields
            og_image=og_image,
            word_count=word_count,
            article_signals=article_signals,
            # Universal metadata fields
            language=self._extract_language(soup),
            canonical_url=self._extract_canonical_url(soup, url),
            article_section=self._extract_article_section(breadcrumbs),
        )
        
        # Compute capability flags (metadata only)
        capabilities = content.compute_capabilities()
        
        self.logger.log_normalization(
            source="html_scraper",
            fields_present=content.get_present_fields(),
            fields_missing=content.get_missing_fields(),
            confidence=confidence,
            url=url
        )
        
        # Log capabilities (metadata for debugging)
        self.logger.log_action(
            "capabilities_computed",
            "completed",
            available=capabilities.get_available_capabilities(),
            missing=capabilities.get_missing_capabilities()
        )
        
        return content
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract page title."""
        # Try og:title first
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            return og_title["content"].strip()
        
        # Fall back to <title> tag
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text().strip()
        
        # Fall back to first H1
        h1 = soup.find("h1")
        if h1:
            return h1.get_text().strip()
        
        return "Untitled Page"
    
    def _extract_meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract meta description."""
        # Try standard meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()
        
        # Try og:description
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            return og_desc["content"].strip()
        
        return None
    
    def _extract_body_text(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract main body text content."""
        # Remove unwanted elements
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        
        # Try to find main content area
        main = soup.find("main") or soup.find("article") or soup.find(class_=re.compile(r"content|post|entry|article", re.I))
        
        if main:
            text = main.get_text(separator=" ", strip=True)
        else:
            body = soup.find("body")
            text = body.get_text(separator=" ", strip=True) if body else ""
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Limit length for practical use
        return text[:5000] if text else None
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[HeadingData]:
        """Extract all headings H1-H6."""
        headings = []
        for level in range(1, 7):
            for h in soup.find_all(f"h{level}"):
                text = h.get_text(strip=True)
                if text:
                    headings.append(HeadingData(level=level, text=text))
        return headings
    
    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[ImageData]:
        """Extract images with src and alt."""
        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src:
                # Make absolute URL
                src = urljoin(base_url, src)
                images.append(ImageData(
                    src=src,
                    alt=img.get("alt"),
                    width=self._parse_int(img.get("width")),
                    height=self._parse_int(img.get("height")),
                ))
        return images[:20]  # Limit to 20 images
    
    def _extract_faq(self, soup: BeautifulSoup) -> List[FAQItem]:
        """Extract FAQ-like patterns from the page."""
        faqs = []
        
        # Look for existing FAQ schema
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "FAQPage":
                    for item in data.get("mainEntity", []):
                        if item.get("@type") == "Question":
                            faqs.append(FAQItem(
                                question=item.get("name", ""),
                                answer=item.get("acceptedAnswer", {}).get("text", "")
                            ))
                    if faqs:
                        return faqs
            except:
                pass
        
        # Look for FAQ-like structures (accordion, dl, etc.)
        # Pattern 1: dt/dd pairs
        for dl in soup.find_all("dl"):
            dts = dl.find_all("dt")
            dds = dl.find_all("dd")
            for dt, dd in zip(dts, dds):
                q = dt.get_text(strip=True)
                a = dd.get_text(strip=True)
                if q and a:
                    faqs.append(FAQItem(question=q, answer=a))
        
        # Pattern 2: Question-like headings followed by paragraphs
        for h in soup.find_all(["h2", "h3", "h4"]):
            text = h.get_text(strip=True)
            if text.endswith("?"):
                next_p = h.find_next_sibling("p")
                if next_p:
                    answer = next_p.get_text(strip=True)
                    if answer:
                        faqs.append(FAQItem(question=text, answer=answer))
        
        return faqs[:10]  # Limit to 10 FAQs
    
    def _extract_breadcrumbs(self, soup: BeautifulSoup, base_url: str) -> List[BreadcrumbItem]:
        """
        Extract breadcrumb navigation.
        
        Priority: JSON-LD (including @graph) > DOM breadcrumbs
        """
        breadcrumbs = []
        
        # Look for existing breadcrumb schema (including @graph format)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)
                
                # Direct BreadcrumbList type
                if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
                    breadcrumbs = self._parse_breadcrumb_list(data)
                    if breadcrumbs:
                        self.logger.log_action(
                            "breadcrumb_extraction",
                            "found_direct_jsonld",
                            count=len(breadcrumbs)
                        )
                        return breadcrumbs
                
                # Handle @graph format - iterate all nodes
                if isinstance(data, dict) and "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") == "BreadcrumbList":
                            breadcrumbs = self._parse_breadcrumb_list(item)
                            if breadcrumbs:
                                self.logger.log_action(
                                    "breadcrumb_extraction",
                                    "found_in_graph",
                                    count=len(breadcrumbs)
                                )
                                return breadcrumbs
                
                # Handle array of schemas
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "BreadcrumbList":
                            breadcrumbs = self._parse_breadcrumb_list(item)
                            if breadcrumbs:
                                self.logger.log_action(
                                    "breadcrumb_extraction",
                                    "found_in_array",
                                    count=len(breadcrumbs)
                                )
                                return breadcrumbs
            except:
                pass
        
        # Fallback: Look for breadcrumb navigation in DOM
        bc_nav = soup.find(attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
        if not bc_nav:
            bc_nav = soup.find(class_=re.compile(r"breadcrumb", re.I))
        
        if bc_nav:
            position = 1
            for a in bc_nav.find_all("a"):
                href = a.get("href")
                name = a.get_text(strip=True)
                if name:
                    breadcrumbs.append(BreadcrumbItem(
                        name=name,
                        url=urljoin(base_url, href) if href else None,
                        position=position
                    ))
                    position += 1
            
            if breadcrumbs:
                self.logger.log_action(
                    "breadcrumb_extraction",
                    "found_in_dom",
                    count=len(breadcrumbs)
                )
        
        return breadcrumbs
    
    def _parse_breadcrumb_list(self, data: dict) -> List[BreadcrumbItem]:
        """Parse a BreadcrumbList JSON-LD object."""
        breadcrumbs = []
        for item in data.get("itemListElement", []):
            name = item.get("name", "")
            url = item.get("item")
            # Handle nested item object
            if isinstance(url, dict):
                url = url.get("@id") or url.get("url")
            position = item.get("position", len(breadcrumbs) + 1)
            if name:
                breadcrumbs.append(BreadcrumbItem(
                    name=name,
                    url=url,
                    position=position
                ))
        return breadcrumbs
    
    def _detect_content_type(
        self, 
        soup: BeautifulSoup, 
        url: str, 
        headings: List[HeadingData],
        faq: List[FAQItem],
        body: Optional[str] = None
    ) -> Tuple[ContentType, List[str]]:
        """
        Detect the type of content using hardened, deterministic classification.
        
        Priority Order:
        1. Product (absolute - never override)
        2. Explicit JSON-LD type (authoritative)
        3. Article/BlogPosting (≥2 signals, no commerce)
        4. URL-based (weak signal)
        5. FAQ (≥3 structured Q&A)
        6. Home page
        7. WebPage (fallback)
        
        Returns: (ContentType, list of signals used)
        """
        url_lower = url.lower()
        article_signals = []
        commerce_signals = []
        jsonld_type = None
        
        # =====================================================================
        # STEP 1: Detect Commerce Signals (BLOCKING for Article)
        # =====================================================================
        
        # Check for price in DOM
        price_elem = soup.find(class_=re.compile(r"price", re.I))
        if price_elem and re.search(r"[\$€£¥]\s*\d", price_elem.get_text()):
            commerce_signals.append("price_visible")
        
        # Check for add to cart buttons
        add_to_cart = soup.find(string=re.compile(r"add to (cart|bag|basket)", re.I))
        if add_to_cart:
            commerce_signals.append("add_to_cart")
        
        # Check for variant selectors
        variant_selectors = soup.find(attrs={"name": re.compile(r"variant|size|color", re.I)})
        if variant_selectors:
            commerce_signals.append("variant_selector")
        
        # Check for checkout/buy CTA
        checkout_cta = soup.find(string=re.compile(r"(buy now|checkout|purchase)", re.I))
        if checkout_cta:
            commerce_signals.append("checkout_cta")
        
        # URL commerce patterns
        if any(p in url_lower for p in ["/product", "/products", "/shop/", "/cart", "/checkout"]):
            commerce_signals.append("commerce_url")
        
        # =====================================================================
        # STEP 2: Collect Article Signals
        # =====================================================================
        
        if soup.find("article"):
            article_signals.append("article_element")
        
        if soup.find("meta", property="article:published_time"):
            article_signals.append("published_time")
        
        if soup.find("meta", property="article:modified_time"):
            article_signals.append("modified_time")
        
        if soup.find("meta", property="article:author"):
            article_signals.append("article_author_meta")
        
        has_author = (
            soup.find("meta", attrs={"name": "author"}) or
            soup.find(attrs={"rel": "author"}) or
            soup.find(class_=re.compile(r"^(author|byline)$", re.I))
        )
        if has_author:
            article_signals.append("author")
        
        if soup.find("time", datetime=True):
            article_signals.append("time_element")
        
        article_url_patterns = ["/blog/", "/news/", "/article/", "/articles/", "/post/", "/posts/",
                                "/technology/", "/science/", "/opinion/", "/features/", "/story/"]
        if any(pattern in url_lower for pattern in article_url_patterns):
            article_signals.append("url_pattern")
        
        if body and len(body.split()) >= 300:
            article_signals.append("long_form_content")
        
        h1_count = len([h for h in headings if h.level == 1])
        if h1_count == 1:
            article_signals.append("single_h1")
        
        # =====================================================================
        # PRIORITY 1: Product (Absolute - Never Override)
        # =====================================================================
        
        # Check JSON-LD for Product FIRST
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                schema_type = self._get_jsonld_type(data)
                if "product" in schema_type.lower():
                    self._log_classification("product", "jsonld_schema", [], commerce_signals)
                    return ContentType.PRODUCT, []
                if schema_type:
                    jsonld_type = schema_type
            except:
                pass
        
        # Commerce signals → Product
        if commerce_signals:
            self._log_classification("product", "commerce_signals", [], commerce_signals)
            return ContentType.PRODUCT, []
        
        # =====================================================================
        # PRIORITY 2: Explicit JSON-LD Type (Authoritative - Trust Over Heuristics)
        # =====================================================================
        
        if jsonld_type:
            jl = jsonld_type.lower()
            if "article" in jl or "blogposting" in jl or "newsarticle" in jl:
                # JSON-LD says Article - trust it
                if "blog" in jl:
                    self._log_classification("blogposting", "jsonld_authoritative", ["jsonld:" + jsonld_type], [])
                    return ContentType.BLOG_POST, ["jsonld:" + jsonld_type]
                else:
                    self._log_classification("article", "jsonld_authoritative", ["jsonld:" + jsonld_type], [])
                    return ContentType.ARTICLE, ["jsonld:" + jsonld_type]
            if "service" in jl:
                return ContentType.SERVICE, ["jsonld:" + jsonld_type]
            if "faqpage" in jl:
                return ContentType.FAQ, ["jsonld:" + jsonld_type]
        
        # =====================================================================
        # PRIORITY 3: Article/BlogPosting (≥2 signals, NO commerce)
        # =====================================================================
        
        # Commerce signals BLOCK Article classification
        if len(article_signals) >= 2 and not commerce_signals:
            is_blog = "/blog" in url_lower or "/post" in url_lower
            
            if is_blog:
                self._log_classification("blogposting", "signal_based", article_signals, [])
                return ContentType.BLOG_POST, article_signals
            else:
                self._log_classification("article", "signal_based", article_signals, [])
                return ContentType.ARTICLE, article_signals
        
        # =====================================================================
        # PRIORITY 4: URL-Based Detection (Weak Signal)
        # =====================================================================
        
        if "/service" in url_lower:
            self._log_classification("service", "url_pattern_weak", [], [])
            return ContentType.SERVICE, []
        if "/about" in url_lower:
            return ContentType.ABOUT, []
        if "/contact" in url_lower:
            return ContentType.CONTACT, []
        if "/faq" in url_lower:
            return ContentType.FAQ, []
        
        # =====================================================================
        # PRIORITY 5: FAQ Detection (Strict - ≥3 structured Q&A)
        # =====================================================================
        
        if len(faq) >= 3:
            return ContentType.FAQ, []
        
        # =====================================================================
        # PRIORITY 6: Home Page Detection
        # =====================================================================
        
        parsed = urlparse(url)
        if parsed.path in ["", "/", "/index.html", "/index.php"]:
            return ContentType.HOME, []
        
        # =====================================================================
        # FALLBACK: WebPage (Single signal NOT enough for Article)
        # =====================================================================
        
        # Single signal → WebPage, NOT Article
        if len(article_signals) == 1:
            self._log_classification("webpage", "single_signal_insufficient", article_signals, [])
        else:
            self._log_classification("webpage", "no_signals", article_signals, [])
        
        return ContentType.UNKNOWN, article_signals
    
    def _get_jsonld_type(self, data: dict) -> str:
        """Extract @type from JSON-LD, handling @graph."""
        if not isinstance(data, dict):
            return ""
        
        # Direct type
        if "@type" in data:
            t = data["@type"]
            if isinstance(t, list):
                return t[0] if t else ""
            return str(t)
        
        # Check @graph for main type
        if "@graph" in data:
            for item in data["@graph"]:
                if isinstance(item, dict) and "@type" in item:
                    t = item["@type"]
                    if isinstance(t, str):
                        if t.lower() in ["article", "blogposting", "newsarticle", "product"]:
                            return t
        
        return ""
    
    def _log_classification(self, decision: str, reason: str, signals: List[str], blocked_by: List[str]):
        """Log classification decision with blocking signals."""
        self.logger.log_action(
            "content_type_decision",
            "decision",
            result=decision,
            reason=reason,
            signals_used=signals,
            signals_blocked=blocked_by,
            signal_count=len(signals)
        )
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract author name using strict, deterministic rules.
        
        PRIORITY ORDER (do NOT merge sources):
        1. JSON-LD author (highest trust)
        2. Semantic HTML author markup
        3. Author page links
        
        RULES:
        - Missing author is acceptable
        - Incorrect author is NOT acceptable
        - Never guess or infer
        
        Returns: Clean author name or None
        """
        # =====================================================================
        # PRIORITY 1: JSON-LD Author (Highest Trust - DO NOT OVERRIDE)
        # =====================================================================
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                author = self._extract_jsonld_author(data)
                if author:
                    clean = self._sanitize_author_name(author)
                    if clean:
                        self.logger.log_action(
                            "author_extraction", "success",
                            source="jsonld", raw=author[:50], clean=clean
                        )
                        return clean
            except:
                pass
        
        # =====================================================================
        # PRIORITY 2: Semantic HTML Author Markup
        # =====================================================================
        
        # 2a: <meta name="author">
        author_meta = soup.find("meta", attrs={"name": "author"})
        if author_meta and author_meta.get("content"):
            clean = self._sanitize_author_name(author_meta["content"])
            if clean:
                self.logger.log_action(
                    "author_extraction", "success",
                    source="meta_name_author", clean=clean
                )
                return clean
        
        # 2b: [itemprop="author"]
        itemprop_author = soup.find(attrs={"itemprop": "author"})
        if itemprop_author:
            # Try to get name from nested element or text
            name_elem = itemprop_author.find(attrs={"itemprop": "name"})
            if name_elem:
                text = name_elem.get_text(strip=True)
            else:
                text = itemprop_author.get_text(strip=True)
            clean = self._sanitize_author_name(text)
            if clean:
                self.logger.log_action(
                    "author_extraction", "success",
                    source="itemprop_author", clean=clean
                )
                return clean
        
        # 2c: [rel="author"]
        rel_author = soup.find(attrs={"rel": "author"})
        if rel_author:
            text = rel_author.get_text(strip=True)
            clean = self._sanitize_author_name(text)
            if clean:
                self.logger.log_action(
                    "author_extraction", "success",
                    source="rel_author", clean=clean
                )
                return clean
        
        # 2d: <address> containing a name (semantic HTML5)
        address = soup.find("address")
        if address:
            # Look for a link or plain text
            link = address.find("a")
            if link:
                text = link.get_text(strip=True)
            else:
                text = address.get_text(strip=True)
            clean = self._sanitize_author_name(text)
            if clean:
                self.logger.log_action(
                    "author_extraction", "success",
                    source="address_element", clean=clean
                )
                return clean
        
        # 2e: Specific author class patterns (exact match only)
        author_classes = [
            "author-name", "post-author-name", "byline-name",
            "article-author-name", "entry-author-name", "author__name"
        ]
        for cls in author_classes:
            elem = soup.find(class_=re.compile(f"^{cls}$", re.I))
            if elem:
                text = elem.get_text(strip=True)
                clean = self._sanitize_author_name(text)
                if clean:
                    self.logger.log_action(
                        "author_extraction", "success",
                        source=f"class_{cls}", clean=clean
                    )
                    return clean
        
        # =====================================================================
        # PRIORITY 3: Author Page Links
        # =====================================================================
        
        # Look for links to /author/ or /writers/ pages on same domain
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "/author/" in href or "/writers/" in href:
                text = link.get_text(strip=True)
                clean = self._sanitize_author_name(text)
                if clean:
                    self.logger.log_action(
                        "author_extraction", "success",
                        source="author_page_link", clean=clean
                    )
                    return clean
        
        # =====================================================================
        # NO VALID AUTHOR FOUND - This is acceptable
        # =====================================================================
        self.logger.log_action(
            "author_extraction", "omitted",
            reason="no_valid_author_signal"
        )
        return None
    
    def _extract_jsonld_author(self, data: dict) -> Optional[str]:
        """Extract author from JSON-LD structure."""
        if not isinstance(data, dict):
            return None
        
        # Direct author field
        author = data.get("author")
        if author:
            if isinstance(author, dict) and author.get("name"):
                return author["name"].strip()
            elif isinstance(author, str):
                return author.strip()
            elif isinstance(author, list) and author:
                first = author[0]
                if isinstance(first, dict) and first.get("name"):
                    return first["name"].strip()
                elif isinstance(first, str):
                    return first.strip()
        
        # Check @graph
        if "@graph" in data:
            for item in data["@graph"]:
                if isinstance(item, dict):
                    item_type = item.get("@type", "")
                    # Look for Article/BlogPosting with author
                    if item_type in ["Article", "BlogPosting", "NewsArticle"]:
                        author = item.get("author")
                        if isinstance(author, dict) and author.get("name"):
                            return author["name"].strip()
                        elif isinstance(author, str):
                            return author.strip()
        
        return None
    
    def _sanitize_author_name(self, raw: str) -> Optional[str]:
        """
        Sanitize and validate author name.
        
        STRICT RULES:
        - Must be ≤80 characters
        - No newlines
        - No URLs
        - No dates
        - No verbs (written, posted, published)
        - No social/share text
        
        Returns: Clean name or None if invalid
        """
        if not raw:
            return None
        
        # Remove "By " prefix
        clean = re.sub(r'^by\s+', '', raw, flags=re.I)
        
        # Remove newlines and normalize whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # Check length (≤80 chars per spec)
        if len(clean) > 80:
            return None
        
        # Reject if too short (single char)
        if len(clean) < 2:
            return None
        
        # Reject if contains URLs
        if re.search(r'https?://', clean, re.I):
            return None
        
        # Reject if contains email
        if '@' in clean and '.' in clean:
            return None
        
        lower = clean.lower()
        
        # Reject if contains verbs (indicates sentence, not name)
        verbs = ['written', 'posted', 'published', 'updated', 'edited', 'reviewed', 'contributed']
        if any(verb in lower for verb in verbs):
            return None
        
        # Reject if contains social/share/UI junk
        ui_junk = [
            'share', 'follow', 'subscribe', 'comment', 'read more',
            'click', 'twitter', 'facebook', 'linkedin', 'instagram',
            'min read', 'comments', 'likes', 'views'
        ]
        if any(junk in lower for junk in ui_junk):
            return None
        
        # Reject if contains date patterns
        if re.search(r'\b\d{4}\b|\b\d{1,2}/\d{1,2}\b', lower):
            return None
        
        # Reject month names (indicates date, not name)
        months = ['january', 'february', 'march', 'april', 'may', 'june', 
                  'july', 'august', 'september', 'october', 'november', 'december',
                  'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
        if any(month in lower for month in months):
            return None
        
        # Reject if too many punctuation marks
        if len(re.findall(r'[.,;:!?(){}[\]|·]', clean)) > 2:
            return None
        
        # Reject if looks like a paragraph
        if clean.count('.') > 1 and len(clean) > 40:
            return None
        
        # Reject if just numbers or mostly numbers
        if re.match(r'^[\d\s]+$', clean):
            return None
        
        return clean
    
    def _extract_date(self, soup: BeautifulSoup, date_type: str) -> Optional[str]:
        """Extract published or modified date."""
        if date_type == "published":
            meta = soup.find("meta", property="article:published_time")
        else:
            meta = soup.find("meta", property="article:modified_time")
        
        if meta and meta.get("content"):
            return meta["content"]
        
        # Try time elements
        time_elem = soup.find("time", attrs={"datetime": True})
        if time_elem:
            return time_elem["datetime"]
        
        return None
    
    def _extract_language(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract page language.
        
        Sources (priority order):
        1. <html lang="...">
        2. <meta http-equiv="content-language">
        
        Returns: Language code (e.g., "en", "en-US") or None
        """
        # Priority 1: html lang attribute
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            lang = html_tag["lang"].strip()
            if lang and len(lang) <= 10:  # Valid language codes are short
                return lang
        
        # Priority 2: meta content-language
        meta_lang = soup.find("meta", attrs={"http-equiv": "content-language"})
        if meta_lang and meta_lang.get("content"):
            return meta_lang["content"].strip()
        
        return None
    
    def _extract_canonical_url(self, soup: BeautifulSoup, fallback_url: str) -> str:
        """
        Extract canonical URL.
        
        Sources:
        1. <link rel="canonical">
        2. og:url
        3. Fallback to provided URL (stripped of tracking params)
        
        Returns: Clean canonical URL
        """
        # Priority 1: link rel="canonical"
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            url = canonical["href"].strip()
            if url.startswith("http"):
                return self._strip_tracking_params(url)
        
        # Priority 2: og:url
        og_url = soup.find("meta", property="og:url")
        if og_url and og_url.get("content"):
            url = og_url["content"].strip()
            if url.startswith("http"):
                return self._strip_tracking_params(url)
        
        # Fallback: strip tracking from provided URL
        return self._strip_tracking_params(fallback_url)
    
    def _strip_tracking_params(self, url: str) -> str:
        """Strip tracking parameters and fragments from URL."""
        # Remove fragment
        if "#" in url:
            url = url.split("#")[0]
        
        # Remove common tracking parameters
        if "?" in url:
            base, query = url.split("?", 1)
            params = query.split("&")
            clean_params = []
            tracking_prefixes = ["utm_", "fbclid", "gclid", "ref", "source", "campaign"]
            for param in params:
                key = param.split("=")[0].lower()
                if not any(key.startswith(p) for p in tracking_prefixes):
                    clean_params.append(param)
            if clean_params:
                url = base + "?" + "&".join(clean_params)
            else:
                url = base
        
        return url
    
    def _extract_article_section(self, breadcrumbs: List[BreadcrumbItem]) -> Optional[str]:
        """
        Extract article section from breadcrumbs.
        
        Uses the last breadcrumb before the article itself (i.e., the category).
        
        Returns: Section name or None
        """
        if not breadcrumbs or len(breadcrumbs) < 2:
            return None
        
        # The category is typically the second-to-last item
        # (last is the article, first is Home)
        if len(breadcrumbs) >= 2:
            # Get the item before the last one
            section = breadcrumbs[-2].name
            if section and section.lower() not in ["home", "index"]:
                return section
        
        # Try the second item if we have at least 3
        if len(breadcrumbs) >= 3:
            section = breadcrumbs[1].name
            if section and section.lower() not in ["home", "index"]:
                return section
        
        return None
    
    def _extract_organization(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract organization name."""
        # Try og:site_name
        site_name = soup.find("meta", property="og:site_name")
        if site_name and site_name.get("content"):
            return site_name["content"].strip()
        
        return None
    
    def _extract_og_image(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """
        Extract Open Graph image.
        
        Priority:
        1. og:image meta tag (preferred for articles)
        2. twitter:image meta tag
        3. First large image in content
        """
        # Try og:image first
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_url = og_image["content"]
            # Ensure absolute URL
            if not img_url.startswith("http"):
                img_url = urljoin(base_url, img_url)
            return img_url
        
        # Try twitter:image
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            img_url = twitter_image["content"]
            if not img_url.startswith("http"):
                img_url = urljoin(base_url, img_url)
            return img_url
        
        return None
    
    def _extract_logo(self, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """
        Extract organization logo.
        
        Priority:
        1. JSON-LD logo (most reliable for publishers)
        2. Header logo image
        3. Site logo image
        4. Apple touch icon (high quality)
        5. Favicon (last resort)
        
        ❌ Do NOT reuse article hero image as logo
        """
        # Priority 1: JSON-LD publisher logo
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                
                # Direct publisher logo
                publisher = data.get("publisher")
                if isinstance(publisher, dict):
                    logo = publisher.get("logo")
                    if isinstance(logo, dict) and logo.get("url"):
                        logo_url = logo["url"]
                        if not logo_url.startswith("http"):
                            logo_url = urljoin(base_url, logo_url)
                        return logo_url
                    elif isinstance(logo, str):
                        if not logo.startswith("http"):
                            logo = urljoin(base_url, logo)
                        return logo
                
                # @graph publisher logo
                if "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict):
                            if item.get("@type") == "Organization":
                                logo = item.get("logo")
                                if isinstance(logo, dict) and logo.get("url"):
                                    logo_url = logo["url"]
                                    if not logo_url.startswith("http"):
                                        logo_url = urljoin(base_url, logo_url)
                                    return logo_url
                                elif isinstance(logo, str):
                                    if not logo.startswith("http"):
                                        logo = urljoin(base_url, logo)
                                    return logo
            except:
                pass
        
        # Priority 2: Header logo image
        header = soup.find("header")
        if header:
            # Look for img with logo class
            logo = header.find("img", class_=re.compile(r"logo", re.I))
            if logo and logo.get("src"):
                return urljoin(base_url, logo["src"])
            # Look for any img that might be a logo (first image in header, likely logo)
            first_img = header.find("img")
            if first_img and first_img.get("src"):
                src = first_img.get("src")
                # Only use if it looks like a logo path
                if "logo" in src.lower() or "brand" in src.lower():
                    return urljoin(base_url, src)
        
        # Priority 3: Site logo anywhere in page
        logo = soup.find("img", class_=re.compile(r"^(site-logo|brand-logo|company-logo)$", re.I))
        if logo and logo.get("src"):
            return urljoin(base_url, logo["src"])
        
        # Any logo class
        logo = soup.find("img", class_=re.compile(r"logo", re.I))
        if logo and logo.get("src"):
            return urljoin(base_url, logo["src"])
        
        # Priority 4: Apple touch icon (high quality, good fallback)
        apple_icon = soup.find("link", rel="apple-touch-icon")
        if apple_icon and apple_icon.get("href"):
            return urljoin(base_url, apple_icon["href"])
        
        # Apple touch icon with sizes
        apple_icons = soup.find_all("link", rel=re.compile(r"apple-touch-icon"))
        if apple_icons:
            # Prefer largest size
            best = None
            best_size = 0
            for icon in apple_icons:
                href = icon.get("href")
                sizes = icon.get("sizes", "0x0")
                try:
                    size = int(sizes.split("x")[0])
                except:
                    size = 0
                if href and size > best_size:
                    best = href
                    best_size = size
            if best:
                return urljoin(base_url, best)
        
        # Priority 5: Favicon (last resort, may be small)
        favicon = soup.find("link", rel="icon")
        if favicon and favicon.get("href"):
            href = favicon["href"]
            # Skip SVG and very small icons
            if ".svg" not in href.lower() and ".ico" not in href.lower():
                return urljoin(base_url, href)
        
        return None
    
    def _calculate_confidence(
        self, 
        title: str, 
        description: Optional[str],
        body: Optional[str],
        headings: List[HeadingData]
    ) -> float:
        """Calculate confidence score based on extracted data quality."""
        score = 0.0
        
        # Title quality
        if title and title != "Untitled Page":
            score += 0.25
        
        # Description present
        if description and len(description) > 50:
            score += 0.25
        elif description:
            score += 0.15
        
        # Body content
        if body and len(body) > 500:
            score += 0.25
        elif body:
            score += 0.15
        
        # Headings structure
        if len(headings) >= 3:
            score += 0.25
        elif headings:
            score += 0.15
        
        return min(score, 1.0)
    
    def _parse_int(self, value: Optional[str]) -> Optional[int]:
        """Safely parse integer from string."""
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None
    
    # =========================================================================
    # UNIFIED JSON-LD PARSING (SINGLE PASS)
    # =========================================================================
    #
    # Parse ALL <script type="application/ld+json"> scripts exactly ONCE.
    # Flatten @graph containers into individual schema nodes.
    # Route nodes by @type for downstream processors.
    #
    # This eliminates redundant parsing and ensures consistent traversal.
    # =========================================================================
    
    def _parse_all_jsonld(self, soup: BeautifulSoup) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parse ALL JSON-LD scripts and organize by @type.
        
        This is the SINGLE source of truth for JSON-LD data.
        All downstream functions should use this instead of re-parsing.
        
        Returns:
            Dict mapping @type to list of schema nodes:
            {
                "Product": [...],
                "BreadcrumbList": [...],
                "Organization": [...],
                "WebPage": [...],
                ...
            }
        """
        nodes_by_type: Dict[str, List[Dict[str, Any]]] = {}
        all_nodes = []
        
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                
                data = json.loads(script.string)
                
                # Collect all schema nodes from this script
                script_nodes = self._flatten_jsonld(data)
                all_nodes.extend(script_nodes)
                
            except json.JSONDecodeError:
                continue
            except Exception:
                continue
        
        # Organize by @type
        for node in all_nodes:
            schema_type = node.get("@type")
            if schema_type:
                # Handle array types (e.g., ["Product", "SomeOtherType"])
                if isinstance(schema_type, list):
                    for t in schema_type:
                        if t not in nodes_by_type:
                            nodes_by_type[t] = []
                        nodes_by_type[t].append(node)
                else:
                    if schema_type not in nodes_by_type:
                        nodes_by_type[schema_type] = []
                    nodes_by_type[schema_type].append(node)
        
        # Log what was found
        types_found = {k: len(v) for k, v in nodes_by_type.items()}
        if types_found:
            self.logger.log_action(
                "jsonld_unified_parse",
                "completed",
                types_found=types_found,
                total_nodes=len(all_nodes)
            )
        else:
            self.logger.log_action(
                "jsonld_unified_parse",
                "no_jsonld_found"
            )
        
        return nodes_by_type
    
    def _flatten_jsonld(self, data: Any) -> List[Dict[str, Any]]:
        """
        Flatten JSON-LD structure into a list of schema nodes.
        
        Handles:
        - Single object with @type
        - @graph containers
        - Arrays of objects
        - Nested structures
        """
        nodes = []
        
        if isinstance(data, dict):
            # Check for @graph (container of multiple schemas)
            if "@graph" in data:
                for item in data["@graph"]:
                    nodes.extend(self._flatten_jsonld(item))
            
            # If this dict has @type, it's a schema node
            if "@type" in data:
                nodes.append(data)
        
        elif isinstance(data, list):
            # Array of schema objects
            for item in data:
                nodes.extend(self._flatten_jsonld(item))
        
        return nodes
    
    def _extract_breadcrumbs_unified(
        self, 
        soup: BeautifulSoup, 
        base_url: str, 
        jsonld_graph: Dict[str, List[Dict[str, Any]]]
    ) -> List[BreadcrumbItem]:
        """
        Extract breadcrumbs using unified JSON-LD graph.
        
        Priority: JSON-LD BreadcrumbList > DOM breadcrumbs
        
        Uses pre-parsed JSON-LD (no re-parsing).
        """
        breadcrumbs = []
        
        # Try JSON-LD first (from unified parser)
        breadcrumb_nodes = jsonld_graph.get("BreadcrumbList", [])
        for bc_data in breadcrumb_nodes:
            parsed = self._parse_breadcrumb_list(bc_data)
            if parsed:
                self.logger.log_action(
                    "breadcrumb_extraction",
                    "from_jsonld_unified",
                    count=len(parsed)
                )
                return parsed
        
        # Fallback: DOM breadcrumbs
        bc_nav = soup.find(attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
        if not bc_nav:
            bc_nav = soup.find(class_=re.compile(r"breadcrumb", re.I))
        
        if bc_nav:
            position = 1
            for a in bc_nav.find_all("a"):
                href = a.get("href")
                name = a.get_text(strip=True)
                if name:
                    breadcrumbs.append(BreadcrumbItem(
                        name=name,
                        url=urljoin(base_url, href) if href else None,
                        position=position
                    ))
                    position += 1
            
            if breadcrumbs:
                self.logger.log_action(
                    "breadcrumb_extraction",
                    "from_dom_fallback",
                    count=len(breadcrumbs)
                )
        
        return breadcrumbs
    
    # =========================================================================
    # PRODUCT DATA EXTRACTION - Three Independent Source-Based Layers
    # =========================================================================
    #
    # Layer 1: Visible DOM Extraction (confidence: 0.6)
    #          - Price text nodes
    #          - Availability text
    #          - Variant labels
    #          - Delivery/shipping text
    #
    # Layer 2: JSON-LD Extraction (confidence: 0.9)
    #          - Product schema (from unified parser)
    #          - Offer schema
    #          - AggregateRating schema
    #
    # Layer 3: Embedded JS State Extraction (confidence: 0.8)
    #          - window.product / window.__INITIAL_STATE__
    #          - ShopifyAnalytics.meta.product
    #          - Generic product JSON blobs
    #
    # Merging: Trust-based precedence (JSON-LD wins for most fields)
    # =========================================================================
    
    def _extract_script_json_data(
        self, 
        soup: BeautifulSoup,
        jsonld_graph: Optional[Dict[str, List[Dict[str, Any]]]] = None
    ) -> Dict[str, Any]:
        """
        Extract product data from multiple sources using independent layers.
        
        Each layer is independent and returns partial product data.
        Merging uses trust-based precedence (JSON-LD > JS State > DOM).
        
        Args:
            soup: Parsed HTML
            jsonld_graph: Pre-parsed JSON-LD organized by @type (from unified parser)
        """
        self.logger.log_action("product_extraction", "started")
        
        # Track extraction sources for logging
        sources_found = []
        
        # Layer 1: Visible DOM extraction (lowest trust: 0.6)
        dom_data = self._extract_from_visible_dom(soup)
        if dom_data:
            sources_found.append(("dom", 0.6, list(dom_data.keys())))
        
        # Layer 2: JSON-LD extraction (highest trust: 0.9)
        # Use pre-parsed graph if available (no re-parsing)
        jsonld_data = self._extract_from_jsonld_layer_unified(jsonld_graph) if jsonld_graph else self._extract_from_jsonld_layer(soup)
        if jsonld_data:
            sources_found.append(("jsonld", 0.9, list(jsonld_data.keys())))
        
        # Layer 3: Embedded JS State extraction (medium trust: 0.8)
        js_state_data = self._extract_from_js_state_layer(soup)
        if js_state_data:
            sources_found.append(("js_state", 0.8, list(js_state_data.keys())))
        
        # Use trust-based merge (not order-based)
        # This ensures JSON-LD always wins for price/offers/rating
        result = self._trust_based_merge(dom_data, js_state_data, jsonld_data)
        
        # Log extraction summary
        extracted_fields = [k for k, v in result.items() if v]
        if sources_found:
            self.logger.log_action(
                "product_extraction",
                "completed",
                sources=[(s[0], s[2]) for s in sources_found],
                final_fields=extracted_fields
            )
        else:
            self.logger.log_action(
                "product_extraction",
                "no_data_found",
                reason="No product data found in DOM, JSON-LD, or JS state"
            )
        
        return result
    
    # =========================================================================
    # LAYER 1: Visible DOM Extraction (Confidence: 0.6)
    # =========================================================================
    
    def _extract_from_visible_dom(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Extract product data from visible DOM elements.
        
        Looks for:
        - Price text in common price containers
        - Availability text indicators
        - Variant option labels
        - Delivery/shipping text
        
        Returns partial product data dict, or None if nothing found.
        """
        result = {}
        
        # Price extraction from visible elements
        price_data = self._extract_dom_price(soup)
        if price_data:
            result["product_offer"] = price_data
        
        # Availability from visible indicators
        availability = self._extract_dom_availability(soup)
        if availability and result.get("product_offer"):
            result["product_offer"].availability = availability
        elif availability:
            result["product_offer"] = ProductOffer(
                price="0.00",  # Placeholder - will be overridden by higher confidence source
                currency="USD",
                availability=availability
            )
        
        # Variant labels from visible options
        variants = self._extract_dom_variants(soup)
        if variants:
            result["product_variants"] = variants
        
        # Delivery text (plain text only)
        delivery_text = self._extract_dom_delivery_text(soup)
        if delivery_text:
            result["delivery_text"] = delivery_text
        
        if result:
            self.logger.log_action(
                "dom_extraction",
                "completed",
                fields_found=list(result.keys())
            )
            return result
        
        self.logger.log_action(
            "dom_extraction",
            "no_data_found",
            reason="No price, availability, or variant elements found in visible DOM"
        )
        return None
    
    def _extract_dom_price(self, soup: BeautifulSoup) -> Optional[ProductOffer]:
        """Extract price from visible DOM price containers."""
        # Common price element patterns (source-driven, not brand-specific)
        price_selectors = [
            "[itemprop='price']",
            "[data-price]",
            "[data-product-price]",
            ".price",
            ".product-price",
            ".current-price",
            ".sale-price",
            "[class*='price']",
        ]
        
        for selector in price_selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    # Get price value from attribute or text
                    price_value = (
                        elem.get("content") or 
                        elem.get("data-price") or 
                        elem.get("data-product-price") or
                        elem.get_text(strip=True)
                    )
                    
                    if price_value:
                        parsed = self._parse_price_text(price_value)
                        if parsed:
                            return ProductOffer(
                                price=parsed["price"],
                                currency=parsed.get("currency", "USD"),
                                availability="InStock"  # Default, can be overridden
                            )
            except Exception:
                continue
        
        return None
    
    def _parse_price_text(self, text: str) -> Optional[Dict[str, str]]:
        """Parse price from text, extracting amount and currency."""
        if not text:
            return None
        
        # Remove whitespace and common separators
        text = text.strip()
        
        # Currency symbol to code mapping
        currency_map = {
            "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
            "₹": "INR", "₽": "RUB", "A$": "AUD", "C$": "CAD",
        }
        
        # Detect currency from symbol
        currency = "USD"
        for symbol, code in currency_map.items():
            if symbol in text:
                currency = code
                break
        
        # Extract numeric price value
        # Match patterns like: $29.99, 29.99, 2999, £29.99
        price_match = re.search(r'[\d,]+\.?\d*', text.replace(",", ""))
        if price_match:
            price_str = price_match.group()
            try:
                price_float = float(price_str)
                # Heuristic: if > 1000 and no decimal, might be cents
                if price_float > 1000 and "." not in price_str:
                    price_float = price_float / 100
                return {"price": f"{price_float:.2f}", "currency": currency}
            except ValueError:
                pass
        
        return None
    
    def _extract_dom_availability(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract availability status from visible DOM elements."""
        # Common availability patterns
        availability_selectors = [
            "[itemprop='availability']",
            "[data-availability]",
            ".availability",
            ".stock-status",
            ".in-stock",
            ".out-of-stock",
        ]
        
        for selector in availability_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    href = elem.get("href", "")
                    text = elem.get_text(strip=True).lower()
                    content = elem.get("content", "").lower()
                    
                    # Check href for schema.org URLs
                    if "instock" in href.lower():
                        return "InStock"
                    if "outofstock" in href.lower():
                        return "OutOfStock"
                    if "preorder" in href.lower():
                        return "PreOrder"
                    
                    # Check content attribute
                    if "instock" in content:
                        return "InStock"
                    if "outofstock" in content:
                        return "OutOfStock"
                    
                    # Check text content
                    if "in stock" in text or "available" in text:
                        return "InStock"
                    if "out of stock" in text or "sold out" in text:
                        return "OutOfStock"
                    if "pre-order" in text or "preorder" in text:
                        return "PreOrder"
            except Exception:
                continue
        
        return None
    
    def _extract_dom_variants(self, soup: BeautifulSoup) -> List[ProductVariant]:
        """Extract variant options from visible DOM elements."""
        variants = []
        
        # Common variant selectors
        variant_selectors = [
            "select[name*='option'] option",
            "[data-option-index] option",
            ".variant-option",
            ".swatch-element",
            "[data-value]",
        ]
        
        for selector in variant_selectors:
            try:
                elements = soup.select(selector)
                for elem in elements[:10]:  # Limit to 10 variants
                    value = elem.get("value") or elem.get("data-value") or elem.get_text(strip=True)
                    if value and value not in ["", "Choose an option", "Select"]:
                        variants.append(ProductVariant(
                            name=elem.get_text(strip=True) or value,
                            value=value,
                            price=None,
                            sku=elem.get("data-sku"),
                            available=not elem.has_attr("disabled")
                        ))
                if variants:
                    break  # Found variants, stop searching
            except Exception:
                continue
        
        return variants
    
    def _extract_dom_delivery_text(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract delivery/shipping text from visible DOM."""
        delivery_selectors = [
            "[class*='shipping']",
            "[class*='delivery']",
            "[data-shipping]",
            ".shipping-info",
            ".delivery-info",
        ]
        
        for selector in delivery_selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    text = elem.get_text(strip=True)
                    if text and len(text) < 200:  # Reasonable length
                        return text
            except Exception:
                continue
        
        return None
    
    # =========================================================================
    # LAYER 2: JSON-LD Extraction (Confidence: 0.9)
    # =========================================================================
    
    def _extract_from_jsonld_layer_unified(
        self, 
        jsonld_graph: Dict[str, List[Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """
        Extract product data from pre-parsed JSON-LD graph.
        
        Uses unified parser output (no re-parsing).
        This is the PREFERRED method when jsonld_graph is available.
        """
        result = {}
        
        # Get all Product nodes from unified graph
        product_nodes = jsonld_graph.get("Product", [])
        
        for product_data in product_nodes:
            parsed = self._parse_jsonld_product(product_data)
            if parsed:
                result = self._merge_product_data(result, parsed)
        
        if result:
            self.logger.log_action(
                "jsonld_extraction_unified",
                "completed",
                fields_found=list(result.keys()),
                product_nodes_found=len(product_nodes)
            )
            return result
        
        self.logger.log_action(
            "jsonld_extraction_unified",
            "no_product_found",
            available_types=list(jsonld_graph.keys())
        )
        return None
    
    def _extract_from_jsonld_layer(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Extract product data from JSON-LD structured data.
        
        Looks for:
        - Product schema
        - Offer schema
        - AggregateRating schema
        
        Returns partial product data dict, or None if nothing found.
        """
        result = {}
        
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                if not script.string:
                    continue
                
                data = json.loads(script.string)
                
                # Handle @graph format
                if isinstance(data, dict) and "@graph" in data:
                    for item in data["@graph"]:
                        if item.get("@type") == "Product":
                            parsed = self._parse_jsonld_product(item)
                            if parsed:
                                result = self._merge_product_data(result, parsed)
                
                # Direct Product type
                elif isinstance(data, dict) and data.get("@type") == "Product":
                    parsed = self._parse_jsonld_product(data)
                    if parsed:
                        result = self._merge_product_data(result, parsed)
                
                # Handle array of schemas
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "Product":
                            parsed = self._parse_jsonld_product(item)
                            if parsed:
                                result = self._merge_product_data(result, parsed)
                                
            except json.JSONDecodeError:
                continue
            except Exception:
                continue
        
        if result:
            self.logger.log_action(
                "jsonld_extraction",
                "completed",
                fields_found=list(result.keys())
            )
            return result
        
        self.logger.log_action(
            "jsonld_extraction",
            "no_data_found",
            reason="No Product JSON-LD schema found"
        )
        return None
    
    def _parse_jsonld_product(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse a JSON-LD Product object into normalized format.
        
        Extracts: sku, mpn, gtin, brand, offers, aggregateRating, image
        """
        result = {}
        
        # SKU
        if "sku" in data:
            result["sku"] = str(data["sku"])
        
        # GTIN (alternative to SKU if SKU not present)
        if not result.get("sku"):
            for gtin_key in ["gtin", "gtin13", "gtin12", "gtin8", "gtin14"]:
                if gtin_key in data:
                    result["sku"] = str(data[gtin_key])
                    break
        
        # MPN (Manufacturer Part Number) - separate from SKU
        if "mpn" in data:
            result["mpn"] = str(data["mpn"])
        
        # Brand
        brand = data.get("brand")
        if isinstance(brand, dict):
            result["brand"] = brand.get("name")
        elif isinstance(brand, str):
            result["brand"] = brand
        
        # Images - preserve array if present
        image = data.get("image")
        if image:
            result["product_images"] = self._normalize_jsonld_images(image)
        
        # Offers (price, currency, availability)
        offers = data.get("offers")
        if offers:
            result["product_offer"] = self._parse_offer(offers)
        
        # AggregateRating
        rating = data.get("aggregateRating")
        if rating:
            result["product_rating"] = self._parse_rating(rating)
        
        return result
    
    def _normalize_jsonld_images(self, image_data: Any) -> List[str]:
        """
        Normalize JSON-LD image field to list of URLs.
        
        Handles:
        - String: single URL
        - List[str]: array of URLs
        - List[dict]: array of ImageObject
        - dict: single ImageObject
        """
        images = []
        
        if isinstance(image_data, str):
            images.append(image_data)
        elif isinstance(image_data, list):
            for img in image_data:
                if isinstance(img, str):
                    images.append(img)
                elif isinstance(img, dict):
                    url = img.get("url") or img.get("@id") or img.get("contentUrl")
                    if url:
                        images.append(url)
        elif isinstance(image_data, dict):
            url = image_data.get("url") or image_data.get("@id") or image_data.get("contentUrl")
            if url:
                images.append(url)
        
        return images
    
    # =========================================================================
    # LAYER 3: Embedded JS State Extraction (Confidence: 0.8)
    # =========================================================================
    
    def _extract_from_js_state_layer(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        Extract product data from embedded JavaScript state objects.
        
        Looks for:
        - window.product / window.__INITIAL_STATE__
        - ShopifyAnalytics.meta.product
        - Generic product JSON blobs with structural confirmation
        
        Returns partial product data dict, or None if nothing found.
        """
        result = {}
        
        for script in soup.find_all("script"):
            if not script.string:
                continue
            
            script_text = script.string
            
            # Strategy 1: window.__INITIAL_STATE__ or window.__PRELOADED_STATE__
            initial_state_data = self._extract_initial_state(script_text)
            if initial_state_data:
                result = self._merge_product_data(result, initial_state_data)
            
            # Strategy 2: Product object assignment (window.product = {...})
            product_obj_data = self._extract_product_object(script_text)
            if product_obj_data:
                result = self._merge_product_data(result, product_obj_data)
            
            # Strategy 3: Analytics/meta product data
            analytics_data = self._extract_analytics_product(script_text)
            if analytics_data:
                result = self._merge_product_data(result, analytics_data)
        
        if result:
            self.logger.log_action(
                "js_state_extraction",
                "completed",
                fields_found=list(result.keys())
            )
            return result
        
        self.logger.log_action(
            "js_state_extraction",
            "no_data_found",
            reason="No product data found in embedded JS state"
        )
        return None
    
    def _extract_initial_state(self, script_text: str) -> Optional[Dict[str, Any]]:
        """Extract product from __INITIAL_STATE__ or similar global state objects."""
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
            r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});',
            r'__NEXT_DATA__.*?({.*})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, script_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # Look for product data in common locations
                    product = self._find_product_in_state(data)
                    if product:
                        return self._normalize_js_product(product)
                except Exception:
                    continue
        
        return None
    
    def _extract_product_object(self, script_text: str) -> Optional[Dict[str, Any]]:
        """Extract product from direct object assignment."""
        patterns = [
            r'(?:window\.)?product\s*=\s*(\{[^;]+\});',
            r'var\s+product\s*=\s*(\{[^;]+\});',
            r'const\s+product\s*=\s*(\{[^;]+\});',
            r'let\s+product\s*=\s*(\{[^;]+\});',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, script_text, re.DOTALL)
            if match:
                try:
                    # Try to parse as JSON with some cleanup
                    json_str = self._clean_js_object(match.group(1))
                    data = json.loads(json_str)
                    return self._normalize_js_product(data)
                except Exception:
                    continue
        
        return None
    
    def _extract_analytics_product(self, script_text: str) -> Optional[Dict[str, Any]]:
        """Extract product from analytics or meta objects."""
        patterns = [
            r'ShopifyAnalytics\.meta\s*=\s*(\{.*?\});',
            r'var\s+meta\s*=\s*(\{.*?\"product\".*?\});',
            r'gtag\([^,]+,\s*[^,]+,\s*(\{.*?\"items\".*?\})\)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, script_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    
                    # Navigate to product data
                    product = data.get("product") or data.get("items", [{}])[0] or data
                    
                    if product and isinstance(product, dict):
                        return self._normalize_js_product(product)
                except Exception:
                    continue
        
        return None
    
    def _find_product_in_state(self, data: Any, depth: int = 0) -> Optional[Dict]:
        """Recursively find product object in state tree (max depth 3)."""
        if depth > 3 or not isinstance(data, dict):
            return None
        
        # Check if this looks like a product object
        product_indicators = ["price", "variants", "sku", "title", "name"]
        if sum(1 for k in product_indicators if k in data) >= 2:
            return data
        
        # Look for nested product
        for key in ["product", "products", "productData", "item", "items"]:
            if key in data:
                child = data[key]
                if isinstance(child, dict):
                    return child
                elif isinstance(child, list) and child:
                    return child[0] if isinstance(child[0], dict) else None
        
        # Recursively search (limited depth)
        for value in data.values():
            if isinstance(value, dict):
                result = self._find_product_in_state(value, depth + 1)
                if result:
                    return result
        
        return None
    
    def _normalize_js_product(self, product: Dict) -> Dict[str, Any]:
        """Normalize JavaScript product object to our format."""
        result = {}
        
        # SKU
        for key in ["sku", "id", "product_id", "productId"]:
            if key in product and product[key]:
                result["sku"] = str(product[key])
                break
        
        # Brand
        brand = product.get("brand") or product.get("vendor")
        if isinstance(brand, dict):
            result["brand"] = brand.get("name")
        elif isinstance(brand, str):
            result["brand"] = brand
        
        # Variants
        variants = product.get("variants", [])
        if variants and isinstance(variants, list):
            result["product_variants"] = self._parse_js_variants(variants)
            
            # Get price from first variant if available
            first_variant = variants[0] if variants else {}
            price = first_variant.get("price")
            if price:
                result["product_offer"] = self._create_offer_from_js(first_variant)
        
        # Direct price if no variants
        if not result.get("product_offer"):
            price = product.get("price") or product.get("price_amount")
            if price:
                result["product_offer"] = self._create_offer_from_price(price, product)
        
        return result
    
    def _parse_js_variants(self, variants: List) -> List[ProductVariant]:
        """Parse JavaScript variant array into ProductVariant list."""
        result = []
        for v in variants[:10]:  # Limit to 10
            if not isinstance(v, dict):
                continue
            try:
                name = v.get("title") or v.get("name") or v.get("option1") or "Variant"
                price = v.get("price")
                price_str = None
                if price is not None:
                    price_val = float(price)
                    # If looks like cents (integer and > 100), convert
                    if isinstance(price, int) and price > 100:
                        price_val = price / 100
                    price_str = f"{price_val:.2f}"
                
                result.append(ProductVariant(
                    name=str(name),
                    value=str(name),
                    price=price_str,
                    sku=str(v.get("sku", "")) if v.get("sku") else None,
                    available=v.get("available", True) if isinstance(v.get("available"), bool) else True
                ))
            except Exception:
                continue
        return result
    
    def _create_offer_from_js(self, variant: Dict) -> Optional[ProductOffer]:
        """Create ProductOffer from JS variant data."""
        price = variant.get("price")
        if price is None:
            return None
        
        try:
            price_val = float(price)
            # If looks like cents, convert
            if isinstance(price, int) and price > 100:
                price_val = price / 100
            
            currency = variant.get("currency") or "USD"
            availability = "InStock" if variant.get("available", True) else "OutOfStock"
            
            return ProductOffer(
                price=f"{price_val:.2f}",
                currency=currency,
                availability=availability
            )
        except Exception:
            return None
    
    def _create_offer_from_price(self, price: Any, product: Dict) -> Optional[ProductOffer]:
        """Create ProductOffer from direct price value."""
        try:
            price_val = float(price)
            # If looks like cents, convert
            if isinstance(price, int) and price > 100:
                price_val = price / 100
            
            currency = product.get("currency") or product.get("currency_code") or "USD"
            available = product.get("available", True)
            availability = "InStock" if available else "OutOfStock"
            
            return ProductOffer(
                price=f"{price_val:.2f}",
                currency=currency,
                availability=availability
            )
        except Exception:
            return None
    
    def _clean_js_object(self, js_str: str) -> str:
        """Clean JavaScript object literal for JSON parsing."""
        # Remove trailing commas before } or ]
        js_str = re.sub(r',\s*([}\]])', r'\1', js_str)
        # Quote unquoted keys
        js_str = re.sub(r'(\s*)(\w+)(\s*:)', r'\1"\2"\3', js_str)
        return js_str
    
    # =========================================================================
    # SHARED PARSING UTILITIES
    # =========================================================================
    
    def _parse_offer(self, offers: Any) -> Optional[ProductOffer]:
        """Parse offer data from JSON-LD or other sources."""
        try:
            # Handle array of offers
            if isinstance(offers, list) and len(offers) > 0:
                offers = offers[0]
            
            if not isinstance(offers, dict):
                return None
            
            price = offers.get("price") or offers.get("lowPrice")
            if not price:
                return None
            
            currency = offers.get("priceCurrency", "USD")
            availability = offers.get("availability", "")
            
            # Normalize availability URL to simple status
            if "InStock" in availability or "instock" in availability.lower():
                availability = "InStock"
            elif "OutOfStock" in availability or "outofstock" in availability.lower():
                availability = "OutOfStock"
            elif "PreOrder" in availability:
                availability = "PreOrder"
            elif "LimitedAvailability" in availability:
                availability = "LimitedAvailability"
            else:
                availability = "InStock"  # Default
            
            return ProductOffer(
                price=str(price),
                currency=currency,
                availability=availability,
                price_valid_until=offers.get("priceValidUntil"),
                seller_name=offers.get("seller", {}).get("name") if isinstance(offers.get("seller"), dict) else None
            )
            
        except Exception:
            return None
    
    def _parse_rating(self, rating: Any) -> Optional[AggregateRatingData]:
        """Parse aggregate rating from JSON-LD or other sources."""
        try:
            if not isinstance(rating, dict):
                return None
            
            rating_value = rating.get("ratingValue")
            review_count = rating.get("reviewCount") or rating.get("ratingCount")
            
            if rating_value is None:
                return None
            
            rating_value = float(rating_value)
            
            # Review count is optional but preferred
            if review_count is not None:
                review_count = int(review_count)
            else:
                review_count = 0
            
            if not (0 <= rating_value <= 5):
                return None
            
            return AggregateRatingData(
                rating_value=rating_value,
                review_count=review_count,
                best_rating=float(rating.get("bestRating", 5)),
                worst_rating=float(rating.get("worstRating", 1))
            )
            
        except Exception:
            return None
    
    def _merge_product_data(self, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """Merge new product data into existing, preferring non-None values."""
        for key, value in new.items():
            if value is not None and existing.get(key) is None:
                existing[key] = value
            elif key == "product_variants" and value:
                if not existing.get("product_variants"):
                    existing["product_variants"] = value
        return existing
    
    def _merge_with_confidence(
        self, 
        existing: Dict[str, Any], 
        new: Dict[str, Any], 
        confidence: float
    ) -> Dict[str, Any]:
        """
        Merge product data with confidence-based priority.
        
        Higher confidence data overwrites lower confidence data.
        This is tracked via order of merging calls (lowest first).
        """
        for key, value in new.items():
            if value is not None:
                # Always merge if existing is None or if this is higher confidence
                # (implied by order of calls - we merge low-to-high)
                if existing.get(key) is None:
                    existing[key] = value
                elif key == "product_variants":
                    # For variants, prefer non-empty list
                    if value and not existing.get("product_variants"):
                        existing["product_variants"] = value
        return existing
    
    def _trust_based_merge(
        self,
        dom_data: Optional[Dict[str, Any]],
        js_state_data: Optional[Dict[str, Any]],
        jsonld_data: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Merge product data using trust-based precedence.
        
        Trust hierarchy (field-specific):
        - price/offers: JSON-LD > JS State > DOM
        - availability: JSON-LD > JS State > DOM
        - images: JSON-LD > DOM (preserved as array)
        - rating: JSON-LD > JS State > DOM
        - variants: JS State > JSON-LD > DOM
        - sku/mpn/brand: JSON-LD > JS State > DOM
        - delivery_text: DOM only
        
        Unlike confidence-based merge which uses order,
        this explicitly selects the most trusted source per field.
        """
        result = {
            "sku": None,
            "mpn": None,
            "brand": None,
            "product_offer": None,
            "product_rating": None,
            "product_variants": [],
            "product_images": [],
            "delivery_text": None,
        }
        
        merge_decisions = []
        
        # === SKU: JSON-LD > JS State > DOM ===
        if jsonld_data and jsonld_data.get("sku"):
            result["sku"] = jsonld_data["sku"]
            merge_decisions.append({"field": "sku", "source": "jsonld", "value": result["sku"]})
        elif js_state_data and js_state_data.get("sku"):
            result["sku"] = js_state_data["sku"]
            merge_decisions.append({"field": "sku", "source": "js_state", "value": result["sku"]})
        
        # === MPN: JSON-LD only ===
        if jsonld_data and jsonld_data.get("mpn"):
            result["mpn"] = jsonld_data["mpn"]
            merge_decisions.append({"field": "mpn", "source": "jsonld", "value": result["mpn"]})
        
        # === Brand: JSON-LD > JS State > DOM ===
        if jsonld_data and jsonld_data.get("brand"):
            result["brand"] = jsonld_data["brand"]
            merge_decisions.append({"field": "brand", "source": "jsonld"})
        elif js_state_data and js_state_data.get("brand"):
            result["brand"] = js_state_data["brand"]
            merge_decisions.append({"field": "brand", "source": "js_state"})
        
        # === Product Offer (price/availability): JSON-LD > JS State > DOM ===
        if jsonld_data and jsonld_data.get("product_offer"):
            result["product_offer"] = jsonld_data["product_offer"]
            merge_decisions.append({"field": "product_offer", "source": "jsonld"})
        elif js_state_data and js_state_data.get("product_offer"):
            result["product_offer"] = js_state_data["product_offer"]
            merge_decisions.append({"field": "product_offer", "source": "js_state"})
        elif dom_data and dom_data.get("product_offer"):
            result["product_offer"] = dom_data["product_offer"]
            merge_decisions.append({"field": "product_offer", "source": "dom"})
        
        # === Product Rating: JSON-LD > JS State > DOM ===
        if jsonld_data and jsonld_data.get("product_rating"):
            result["product_rating"] = jsonld_data["product_rating"]
            merge_decisions.append({"field": "product_rating", "source": "jsonld"})
        elif js_state_data and js_state_data.get("product_rating"):
            result["product_rating"] = js_state_data["product_rating"]
            merge_decisions.append({"field": "product_rating", "source": "js_state"})
        
        # === Variants: JS State > JSON-LD > DOM ===
        # (JS state often has better variant data with prices)
        if js_state_data and js_state_data.get("product_variants"):
            result["product_variants"] = js_state_data["product_variants"]
            merge_decisions.append({"field": "product_variants", "source": "js_state", "count": len(result["product_variants"])})
        elif dom_data and dom_data.get("product_variants"):
            result["product_variants"] = dom_data["product_variants"]
            merge_decisions.append({"field": "product_variants", "source": "dom", "count": len(result["product_variants"])})
        
        # === Product Images: JSON-LD > DOM ===
        # (JSON-LD images are canonical, preserve full array)
        if jsonld_data and jsonld_data.get("product_images"):
            result["product_images"] = jsonld_data["product_images"]
            merge_decisions.append({"field": "product_images", "source": "jsonld", "count": len(result["product_images"])})
        
        # === Delivery Text: DOM only ===
        if dom_data and dom_data.get("delivery_text"):
            result["delivery_text"] = dom_data["delivery_text"]
            merge_decisions.append({"field": "delivery_text", "source": "dom"})
        
        # Log merge decisions
        self.logger.log_action(
            "trust_based_merge",
            "completed",
            decisions=merge_decisions
        )
        
        return result
