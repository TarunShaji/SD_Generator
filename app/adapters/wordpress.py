"""
WordPress Adapter for the Structured Data Automation Tool.
Handles both authenticated and unauthenticated WordPress REST API access.
"""
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse, unquote

import httpx

from app.models.content import (
    NormalizedContent,
    SourceType,
    ContentType,
    ImageData,
    HeadingData,
    FAQItem,
    BreadcrumbItem,
)
from app.utils.logger import LayerLogger
from app.config import config


class WordPressAdapter:
    """
    WordPress REST API adapter for content extraction.
    Supports both self-hosted WordPress and WordPress.com.
    """
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.logger = LayerLogger("wordpress_adapter")
        self.access_token: Optional[str] = None
    
    def set_access_token(self, token: str):
        """Set OAuth access token for authenticated requests."""
        self.access_token = token
        self.logger.log_action("set_access_token", "completed")
    
    async def fetch_content(
        self, 
        url: str, 
        site_url: str,
        authenticated: bool = False
    ) -> NormalizedContent:
        """
        Fetch content from WordPress REST API (self-hosted WordPress).
        
        Args:
            url: The page URL to fetch
            site_url: The WordPress site root URL
            authenticated: Whether to use OAuth token
        
        Returns:
            NormalizedContent model
        """
        self.logger.log_action(
            "fetch_wordpress_content", 
            "started", 
            url=url,
            site_url=site_url,
            authenticated=authenticated
        )
        
        # Determine if URL is a post or page
        slug = self._extract_slug(url)
        
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            # Try to find the content by slug
            content_data = await self._find_content_by_slug(client, site_url, slug, authenticated)
            
            if not content_data:
                raise ValueError(f"Could not find WordPress content for URL: {url}")
            
            return self._normalize_content(url, content_data, authenticated)
    
    async def fetch_content_wordpress_com(
        self,
        url: str,
        site_domain: str,
        authenticated: bool = False
    ) -> NormalizedContent:
        """
        Fetch content from WordPress.com PUBLIC API.
        
        This uses the correct endpoint for WordPress.com:
        https://public-api.wordpress.com/rest/v1.1/sites/{domain}/posts
        
        NOT /wp-json/wp/v2/ which doesn't exist on WordPress.com.
        
        Args:
            url: The page URL to fetch
            site_domain: The WordPress.com site domain (e.g., "mysite.wordpress.com")
            authenticated: Whether to use OAuth token
        
        Returns:
            NormalizedContent model
        """
        self.logger.log_action(
            "fetch_wordpress_com_content",
            "started",
            url=url,
            site_domain=site_domain,
            authenticated=authenticated
        )
        
        slug = self._extract_slug(url)
        
        self.logger.log_action(
            "wordpress_com_slug_extraction",
            "completed",
            slug=slug,
            url=url
        )
        
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            content_data = await self._find_content_wordpress_com(
                client, site_domain, slug, authenticated
            )
            
            if not content_data:
                self.logger.log_error(
                    f"Could not find WordPress.com content for URL: {url}",
                    error_type="content_not_found",
                    slug=slug,
                    site_domain=site_domain
                )
                raise ValueError(f"Could not find WordPress.com content for URL: {url}")
            
            return self._normalize_wordpress_com_content(url, content_data, authenticated)
    
    async def _find_content_wordpress_com(
        self,
        client: httpx.AsyncClient,
        site_domain: str,
        slug: str,
        authenticated: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Find content on WordPress.com using the public API.
        
        Tries:
        1. /posts?type=page&slug={slug} (pages)
        2. /posts?type=post&slug={slug} (posts)
        """
        base_url = f"https://public-api.wordpress.com/rest/v1.1/sites/{site_domain}"
        headers = self._get_headers(authenticated)
        
        # =====================================================================
        # TRY PAGES FIRST: /posts?type=page&slug={slug}
        # WordPress.com exposes pages via /posts endpoint with type=page
        # =====================================================================
        
        pages_url = f"{base_url}/posts?type=page&slug={slug}"
        self.logger.log_action(
            "wordpress_com_api_request",
            "trying_pages",
            url=pages_url,
            slug=slug
        )
        
        try:
            response = await client.get(pages_url, headers=headers)
            self.logger.log_action(
                "wordpress_com_api_response",
                "pages",
                status_code=response.status_code,
                slug=slug
            )
            
            if response.status_code == 200:
                data = response.json()
                posts = data.get("posts", [])
                if posts and len(posts) > 0:
                    raw_content = posts[0]
                    
                    # Log the RAW content from WordPress.com BEFORE normalization
                    self.logger.log_action(
                        "wordpress_com_raw_content",
                        "fetched",
                        slug=slug,
                        title=raw_content.get("title", "Unknown"),
                        excerpt=raw_content.get("excerpt", "")[:200] + "..." if raw_content.get("excerpt") else None,
                        content_length=len(raw_content.get("content", "")),
                        author=raw_content.get("author", {}).get("name") if isinstance(raw_content.get("author"), dict) else None,
                        date=raw_content.get("date"),
                        modified=raw_content.get("modified"),
                        featured_image=raw_content.get("featured_image"),
                        categories=list(raw_content.get("categories", {}).keys())[:5] if raw_content.get("categories") else [],
                        tags=list(raw_content.get("tags", {}).keys())[:5] if raw_content.get("tags") else [],
                    )
                    
                    self.logger.log_action(
                        "wordpress_com_content_found",
                        "page",
                        slug=slug,
                        title=raw_content.get("title", "Unknown")
                    )
                    return {"type": "page", "data": raw_content}
        except Exception as e:
            self.logger.log_error(
                f"Error fetching WordPress.com pages: {e}",
                error_type="api_error",
                slug=slug
            )
        
        # =====================================================================
        # TRY POSTS: /posts?type=post&slug={slug}
        # =====================================================================
        
        posts_url = f"{base_url}/posts?type=post&slug={slug}"
        self.logger.log_action(
            "wordpress_com_api_request",
            "trying_posts",
            url=posts_url,
            slug=slug
        )
        
        try:
            response = await client.get(posts_url, headers=headers)
            self.logger.log_action(
                "wordpress_com_api_response",
                "posts",
                status_code=response.status_code,
                slug=slug
            )
            
            if response.status_code == 200:
                data = response.json()
                posts = data.get("posts", [])
                if posts and len(posts) > 0:
                    raw_content = posts[0]
                    
                    # Log the RAW content from WordPress.com BEFORE normalization
                    self.logger.log_action(
                        "wordpress_com_raw_content",
                        "fetched",
                        slug=slug,
                        title=raw_content.get("title", "Unknown"),
                        excerpt=raw_content.get("excerpt", "")[:200] + "..." if raw_content.get("excerpt") else None,
                        content_length=len(raw_content.get("content", "")),
                        author=raw_content.get("author", {}).get("name") if isinstance(raw_content.get("author"), dict) else None,
                        date=raw_content.get("date"),
                        modified=raw_content.get("modified"),
                        featured_image=raw_content.get("featured_image"),
                        categories=list(raw_content.get("categories", {}).keys())[:5] if raw_content.get("categories") else [],
                        tags=list(raw_content.get("tags", {}).keys())[:5] if raw_content.get("tags") else [],
                    )
                    
                    self.logger.log_action(
                        "wordpress_com_content_found",
                        "post",
                        slug=slug,
                        title=raw_content.get("title", "Unknown")
                    )
                    return {"type": "post", "data": raw_content}
        except Exception as e:
            self.logger.log_error(
                f"Error fetching WordPress.com posts: {e}",
                error_type="api_error",
                slug=slug
            )
        
        self.logger.log_action(
            "wordpress_com_content_not_found",
            "failed",
            slug=slug,
            site_domain=site_domain
        )
        
        return None
    
    def _normalize_wordpress_com_content(
        self,
        url: str,
        content_data: Dict[str, Any],
        authenticated: bool
    ) -> NormalizedContent:
        """
        Normalize WordPress.com API response to standard model.
        
        WordPress.com API returns slightly different structure than /wp-json
        """
        wp_type = content_data["type"]
        data = content_data["data"]
        
        # WordPress.com returns title as string, not {rendered: "..."}
        title = data.get("title", "Untitled")
        body_html = data.get("content", "")
        excerpt = data.get("excerpt", "")
        
        # Parse the HTML content
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body_html, "lxml")
        
        headings = self._extract_headings(soup)
        images = self._extract_images(soup, url)
        faq = self._extract_faq(soup)
        
        body_text = soup.get_text(separator=" ", strip=True)
        body_text = re.sub(r'\s+', ' ', body_text)[:5000]
        
        # Excerpt for WordPress.com
        excerpt_soup = BeautifulSoup(excerpt, "lxml")
        description = excerpt_soup.get_text(strip=True)
        
        # Content type
        if wp_type == "post":
            content_type = ContentType.BLOG_POST
        else:
            content_type = self._detect_page_type(url, title, body_text)
        
        # Dates
        published_date = data.get("date")
        modified_date = data.get("modified")
        
        # Author - WordPress.com returns author object directly
        author = data.get("author", {})
        author_name = author.get("name") if isinstance(author, dict) else None
        
        # Featured image
        featured_image = data.get("featured_image")
        if featured_image:
            images.insert(0, ImageData(src=featured_image, alt=title))
        
        # Confidence
        confidence = 0.9 if body_text else 0.7
        
        source_type = (
            SourceType.WORDPRESS_REST_AUTH
            if authenticated
            else SourceType.WORDPRESS_REST
        )
        
        content = NormalizedContent(
            url=url,
            title=title,
            description=description if description else None,
            body=body_text if body_text else None,
            headings=headings,
            images=images,
            faq=faq,
            breadcrumbs=[],
            content_type=content_type,
            source_type=source_type,
            confidence_score=confidence,
            author=author_name,
            published_date=published_date,
            modified_date=modified_date,
        )
        
        self.logger.log_normalization(
            source="wordpress_com_public_api",
            fields_present=content.get_present_fields(),
            fields_missing=content.get_missing_fields(),
            confidence=confidence,
            url=url
        )
        
        return content
    
    async def _find_content_by_slug(
        self, 
        client: httpx.AsyncClient,
        site_url: str,
        slug: str,
        authenticated: bool
    ) -> Optional[Dict[str, Any]]:
        """Find content by trying different endpoints."""
        headers = self._get_headers(authenticated)
        
        # Try posts first
        posts_url = f"{site_url}/wp-json/wp/v2/posts?slug={slug}"
        try:
            response = await client.get(posts_url, headers=headers)
            if response.status_code == 200:
                posts = response.json()
                if posts and len(posts) > 0:
                    self.logger.log_action(
                        "find_content", 
                        "completed",
                        content_type="post",
                        slug=slug
                    )
                    return {"type": "post", "data": posts[0]}
        except Exception as e:
            self.logger.log_error(f"Error fetching posts: {e}", error_type="api_error")
        
        # Try pages
        pages_url = f"{site_url}/wp-json/wp/v2/pages?slug={slug}"
        try:
            response = await client.get(pages_url, headers=headers)
            if response.status_code == 200:
                pages = response.json()
                if pages and len(pages) > 0:
                    self.logger.log_action(
                        "find_content", 
                        "completed",
                        content_type="page",
                        slug=slug
                    )
                    return {"type": "page", "data": pages[0]}
        except Exception as e:
            self.logger.log_error(f"Error fetching pages: {e}", error_type="api_error")
        
        return None
    
    def _extract_slug(self, url: str) -> str:
        """Extract the slug from a URL."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        
        # Get the last segment
        slug = path.split("/")[-1] if path else ""
        
        # URL decode
        slug = unquote(slug)
        
        # Remove common suffixes
        slug = re.sub(r'\.(html|php|htm)$', '', slug)
        
        return slug
    
    def _get_headers(self, authenticated: bool) -> Dict[str, str]:
        """Get request headers, including auth if needed."""
        headers = {
            "Accept": "application/json",
            "User-Agent": "StructuredDataTool/1.0",
        }
        
        if authenticated and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        
        return headers
    
    def _normalize_content(
        self, 
        url: str, 
        content_data: Dict[str, Any],
        authenticated: bool
    ) -> NormalizedContent:
        """Normalize WordPress content to standard model."""
        wp_type = content_data["type"]
        data = content_data["data"]
        
        title = self._extract_title(data)
        body_html = data.get("content", {}).get("rendered", "")
        excerpt = data.get("excerpt", {}).get("rendered", "")
        
        # Parse the HTML content for structured data
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(body_html, "lxml")
        
        # Extract headings from content
        headings = self._extract_headings(soup)
        
        # Extract images from content
        images = self._extract_images(soup, url)
        
        # Extract FAQs from content
        faq = self._extract_faq(soup)
        
        # Clean body text
        body_text = soup.get_text(separator=" ", strip=True)
        body_text = re.sub(r'\s+', ' ', body_text)[:5000]
        
        # Clean excerpt for description
        excerpt_soup = BeautifulSoup(excerpt, "lxml")
        description = excerpt_soup.get_text(strip=True)
        
        # Determine content type
        if wp_type == "post":
            content_type = ContentType.BLOG_POST
        else:
            content_type = self._detect_page_type(url, title, body_text)
        
        # Get dates
        published_date = data.get("date")
        modified_date = data.get("modified")
        
        # Calculate confidence (WordPress API data is high quality)
        confidence = 0.9 if body_text else 0.7
        
        source_type = (
            SourceType.WORDPRESS_REST_AUTH 
            if authenticated 
            else SourceType.WORDPRESS_REST
        )
        
        content = NormalizedContent(
            url=url,
            title=title,
            description=description if description else None,
            body=body_text if body_text else None,
            headings=headings,
            images=images,
            faq=faq,
            breadcrumbs=[],  # WordPress doesn't provide breadcrumbs via API
            content_type=content_type,
            source_type=source_type,
            confidence_score=confidence,
            author=self._extract_author_name(data),
            published_date=published_date,
            modified_date=modified_date,
        )
        
        self.logger.log_normalization(
            source=source_type.value,
            fields_present=content.get_present_fields(),
            fields_missing=content.get_missing_fields(),
            confidence=confidence,
            url=url
        )
        
        return content
    
    def _extract_title(self, data: Dict[str, Any]) -> str:
        """Extract title from WordPress data."""
        title_data = data.get("title", {})
        if isinstance(title_data, dict):
            return title_data.get("rendered", "Untitled")
        return str(title_data) if title_data else "Untitled"
    
    def _extract_headings(self, soup) -> List[HeadingData]:
        """Extract headings from content HTML."""
        headings = []
        for level in range(1, 7):
            for h in soup.find_all(f"h{level}"):
                text = h.get_text(strip=True)
                if text:
                    headings.append(HeadingData(level=level, text=text))
        return headings
    
    def _extract_images(self, soup, base_url: str) -> List[ImageData]:
        """Extract images from content HTML."""
        from urllib.parse import urljoin
        images = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if src:
                images.append(ImageData(
                    src=urljoin(base_url, src),
                    alt=img.get("alt"),
                    width=self._parse_int(img.get("width")),
                    height=self._parse_int(img.get("height")),
                ))
        return images[:20]
    
    def _extract_faq(self, soup) -> List[FAQItem]:
        """Extract FAQ patterns from content."""
        faqs = []
        
        # Look for FAQ blocks (common in WordPress)
        for h in soup.find_all(["h2", "h3", "h4"]):
            text = h.get_text(strip=True)
            if text.endswith("?"):
                next_elem = h.find_next_sibling(["p", "div"])
                if next_elem:
                    answer = next_elem.get_text(strip=True)
                    if answer:
                        faqs.append(FAQItem(question=text, answer=answer))
        
        return faqs[:10]
    
    def _extract_author_name(self, data: Dict[str, Any]) -> Optional[str]:
        """Extract author name from embedded data."""
        embedded = data.get("_embedded", {})
        author_list = embedded.get("author", [])
        if author_list and len(author_list) > 0:
            return author_list[0].get("name")
        return None
    
    def _detect_page_type(self, url: str, title: str, body: str) -> ContentType:
        """Detect page type for WordPress pages."""
        url_lower = url.lower()
        title_lower = title.lower()
        
        if "/service" in url_lower or "service" in title_lower:
            return ContentType.SERVICE
        if "/about" in url_lower or "about" in title_lower:
            return ContentType.ABOUT
        if "/contact" in url_lower or "contact" in title_lower:
            return ContentType.CONTACT
        if "/faq" in url_lower or "faq" in title_lower:
            return ContentType.FAQ
        
        return ContentType.UNKNOWN
    
    def _parse_int(self, value: Optional[str]) -> Optional[int]:
        """Safely parse integer from string."""
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None
