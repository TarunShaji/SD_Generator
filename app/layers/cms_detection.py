"""
CMS Detection Layer for the Structured Data Automation Tool.
This is Layer 1 - the Gatekeeper that determines CMS type and REST availability.
"""
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.utils.logger import LayerLogger


class CMSType(str, Enum):
    """Detected CMS type."""
    WORDPRESS = "wordpress"
    WORDPRESS_COM = "wordpress_com"  # Hosted WordPress.com
    SHOPIFY = "shopify"
    UNKNOWN = "unknown"


class RESTStatus(str, Enum):
    """REST API availability status."""
    AVAILABLE = "available"
    BLOCKED = "blocked"  # 401/403
    NOT_FOUND = "not_found"  # 404 or no REST
    ERROR = "error"


class AuthRequirement(str, Enum):
    """
    Authentication requirement classification.
    
    Determines what type of authentication is needed based on
    response analysis - NOT assumptions.
    """
    NONE = "none"                          # No auth required (200 OK)
    OAUTH = "oauth"                        # WordPress.com OAuth
    BASIC = "basic"                        # Basic Auth (not implemented)
    APPLICATION_PASSWORD = "application_password"  # WP Application Passwords (not implemented)
    UNKNOWN = "unknown"                    # Blocked but cannot determine method


@dataclass
class CMSDetectionResult:
    """Result of CMS detection."""
    cms_type: CMSType
    rest_status: RESTStatus
    auth_required: AuthRequirement  # NEW: Classified auth requirement
    site_url: str
    confidence: float
    requires_oauth: bool
    oauth_optional: bool
    message: str


class CMSDetectionLayer:
    """
    CMS Detection Layer - determines CMS type and REST availability.
    
    This layer answers: "Can structured page data be retrieved without authentication?"
    
    Key principles:
    - Never triggers OAuth automatically
    - REST-first approach
    - Detailed logging for debugging
    """
    
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.logger = LayerLogger("cms_detection")
    
    async def detect(self, url: str) -> CMSDetectionResult:
        """
        Detect CMS type and REST API availability for a given URL.
        
        Args:
            url: The page URL to analyze
        
        Returns:
            CMSDetectionResult with CMS type and REST status
        """
        self.logger.log_action("cms_detection", "started", url=url)
        
        # Parse URL to get site root
        parsed = urlparse(url)
        site_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try WordPress detection first
        wp_result = await self._detect_wordpress(site_url, url)
        if wp_result.cms_type in [CMSType.WORDPRESS, CMSType.WORDPRESS_COM]:
            return wp_result
        
        # Try Shopify detection
        shopify_result = await self._detect_shopify(site_url, url)
        if shopify_result.cms_type == CMSType.SHOPIFY:
            return shopify_result
        
        # Unknown CMS
        result = CMSDetectionResult(
            cms_type=CMSType.UNKNOWN,
            rest_status=RESTStatus.NOT_FOUND,
            auth_required=AuthRequirement.NONE,
            site_url=site_url,
            confidence=0.0,
            requires_oauth=False,
            oauth_optional=False,
            message="Could not detect CMS type. HTML scraping will be used.",
        )
        
        self.logger.log_decision(
            decision="unknown_cms",
            reason="No WordPress or Shopify markers detected",
            url=url,
            next_step="html_fallback"
        )
        
        return result
    
    async def _detect_wordpress(self, site_url: str, page_url: str) -> CMSDetectionResult:
        """
        Detect WordPress and check REST API availability.
        
        Strategy:
        1. FIRST: Check if domain is *.wordpress.com (early detection)
        2. Probe /wp-json/
        3. 200 OK → WordPress (self-hosted), REST available
        4. 401/403 → WordPress detected, REST blocked (possible WordPress.com)
        5. 404 → Not WordPress
        """
        parsed = urlparse(site_url)
        domain = parsed.netloc.lower()
        
        # =====================================================================
        # EARLY WORDPRESS.COM DETECTION (before /wp-json probe)
        # WordPress.com returns 404 for /wp-json, so detect by domain first
        # =====================================================================
        
        if domain.endswith(".wordpress.com"):
            self.logger.log_action(
                "wordpress_com_early_detection",
                "domain_match",
                domain=domain,
                reason="Domain ends with .wordpress.com"
            )
            
            # Probe WordPress.com public API to confirm
            wpcom_result = await self._detect_wordpress_com_public_api(site_url, page_url, domain)
            if wpcom_result:
                return wpcom_result
            
            # Domain matched but API probe failed - still treat as WordPress.com
            self.logger.log_action(
                "wordpress_com_early_detection",
                "domain_only_fallback",
                domain=domain,
                reason="Public API probe failed, using domain-based detection"
            )
            
            return CMSDetectionResult(
                cms_type=CMSType.WORDPRESS_COM,
                rest_status=RESTStatus.AVAILABLE,
                auth_required=AuthRequirement.OAUTH,
                site_url=site_url,
                confidence=0.90,
                requires_oauth=False,  # Never required
                oauth_optional=True,   # User can choose to connect
                message="WordPress.com detected (domain match). Connect your account for enhanced data or use HTML fallback.",
            )
        
        # =====================================================================
        # STANDARD WORDPRESS DETECTION (self-hosted)
        # =====================================================================
        
        wp_json_url = urljoin(site_url, "/wp-json/")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                self.logger.log_action(
                    "wordpress_probe",
                    "started",
                    endpoint="/wp-json/",
                    url=wp_json_url
                )
                
                response = await client.get(wp_json_url, headers={
                    "Accept": "application/json",
                    "User-Agent": "StructuredDataTool/1.0"
                })
                
                status_code = response.status_code
                
                self.logger.log_http_probe(
                    url=page_url,
                    endpoint="/wp-json/",
                    status_code=status_code,
                    result=self._status_to_result(status_code)
                )
                
                # 200 OK - WordPress with REST available
                if status_code == 200:
                    # Check if it's actually WordPress by examining response
                    try:
                        data = response.json()
                        if "name" in data or "namespaces" in data:
                            self.logger.log_decision(
                                decision="wordpress_detected",
                                reason="REST API returned valid WordPress response",
                                url=page_url,
                                rest_available=True,
                                next_step="use_rest_api"
                            )
                            
                            return CMSDetectionResult(
                                cms_type=CMSType.WORDPRESS,
                                rest_status=RESTStatus.AVAILABLE,
                                auth_required=AuthRequirement.NONE,
                                site_url=site_url,
                                confidence=0.95,
                                requires_oauth=False,
                                oauth_optional=False,
                                message="WordPress detected with REST API available. No authentication required.",
                            )
                    except:
                        pass
                
                # 401/403 - WordPress detected but REST blocked
                if status_code in [401, 403]:
                    # This could be WordPress.com or a locked self-hosted site
                    is_wpcom = await self._is_wordpress_com(site_url, client)
                    
                    if is_wpcom:
                        self.logger.log_decision(
                            decision="auth_classification",
                            reason="wordpress_dot_com_detected",
                            url=page_url,
                            auth_required="oauth"
                        )
                        self.logger.log_decision(
                            decision="wordpress_com_detected",
                            reason="REST blocked with WordPress.com markers",
                            url=page_url,
                            rest_available=False,
                            oauth_optional=True,
                            next_step="offer_oauth_or_html_fallback"
                        )
                        
                        return CMSDetectionResult(
                            cms_type=CMSType.WORDPRESS_COM,
                            rest_status=RESTStatus.BLOCKED,
                            auth_required=AuthRequirement.OAUTH,
                            site_url=site_url,
                            confidence=0.85,
                            requires_oauth=False,  # Never required
                            oauth_optional=True,   # User can choose to connect
                            message="WordPress.com detected. REST API requires authentication. You can connect your account or use HTML fallback.",
                        )
                    else:
                        self.logger.log_decision(
                            decision="auth_classification",
                            reason="self_hosted_wp_rest_blocked",
                            url=page_url,
                            auth_required="unknown"
                        )
                        self.logger.log_decision(
                            decision="wordpress_locked_detected",
                            reason="REST blocked on self-hosted site - auth type cannot be determined",
                            url=page_url,
                            rest_available=False,
                            next_step="html_fallback"
                        )
                        
                        return CMSDetectionResult(
                            cms_type=CMSType.WORDPRESS,
                            rest_status=RESTStatus.BLOCKED,
                            auth_required=AuthRequirement.UNKNOWN,
                            site_url=site_url,
                            confidence=0.75,
                            requires_oauth=False,
                            oauth_optional=False,  # Self-hosted can't use WordPress.com OAuth
                            message="This site's REST API is restricted. Authentication may be required (plugin, application password, or firewall). Falling back to HTML scraping.",
                        )
                
                # 404 or other - Not WordPress (at least via REST)
                return CMSDetectionResult(
                    cms_type=CMSType.UNKNOWN,
                    rest_status=RESTStatus.NOT_FOUND,
                    auth_required=AuthRequirement.NONE,
                    site_url=site_url,
                    confidence=0.0,
                    requires_oauth=False,
                    oauth_optional=False,
                    message="WordPress REST API not found.",
                )
                
        except httpx.TimeoutException:
            self.logger.log_error(
                "Timeout while probing WordPress REST API",
                error_type="timeout",
                url=page_url,
                endpoint="/wp-json/"
            )
            return CMSDetectionResult(
                cms_type=CMSType.UNKNOWN,
                rest_status=RESTStatus.ERROR,
                auth_required=AuthRequirement.NONE,
                site_url=site_url,
                confidence=0.0,
                requires_oauth=False,
                oauth_optional=False,
                message="Timeout while detecting CMS.",
            )
        except Exception as e:
            self.logger.log_error(
                f"Error while probing WordPress: {str(e)}",
                error_type="detection_error",
                url=page_url
            )
            return CMSDetectionResult(
                cms_type=CMSType.UNKNOWN,
                rest_status=RESTStatus.ERROR,
                auth_required=AuthRequirement.NONE,
                site_url=site_url,
                confidence=0.0,
                requires_oauth=False,
                oauth_optional=False,
                message=f"Error during CMS detection: {str(e)}",
            )
    
    async def _detect_wordpress_com_public_api(
        self, 
        site_url: str, 
        page_url: str, 
        domain: str
    ) -> Optional[CMSDetectionResult]:
        """
        Probe WordPress.com public API to confirm site accessibility.
        
        Uses: https://public-api.wordpress.com/rest/v1.1/sites/{domain}
        
        This is the correct API for WordPress.com sites, NOT /wp-json.
        """
        public_api_url = f"https://public-api.wordpress.com/rest/v1.1/sites/{domain}"
        
        self.logger.log_action(
            "wordpress_com_public_api_probe",
            "started",
            domain=domain,
            api_url=public_api_url
        )
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(public_api_url, headers={
                    "Accept": "application/json",
                    "User-Agent": "StructuredDataTool/1.0"
                })
                
                status_code = response.status_code
                
                self.logger.log_http_probe(
                    url=page_url,
                    endpoint=f"/rest/v1.1/sites/{domain}",
                    status_code=status_code,
                    result=self._status_to_result(status_code)
                )
                
                if status_code == 200:
                    try:
                        data = response.json()
                        site_name = data.get("name", "Unknown")
                        is_private = data.get("is_private", False)
                        
                        self.logger.log_action(
                            "wordpress_com_public_api_probe",
                            "success",
                            site_name=site_name,
                            is_private=is_private,
                            domain=domain
                        )
                        
                        self.logger.log_decision(
                            decision="wordpress_com_confirmed",
                            reason="Public API returned valid site info",
                            url=page_url,
                            site_name=site_name,
                            is_private=is_private,
                            next_step="offer_oauth_or_html_fallback"
                        )
                        
                        return CMSDetectionResult(
                            cms_type=CMSType.WORDPRESS_COM,
                            rest_status=RESTStatus.AVAILABLE,
                            auth_required=AuthRequirement.OAUTH,
                            site_url=site_url,
                            confidence=0.95,
                            requires_oauth=False,  # Never required
                            oauth_optional=True,   # User can choose
                            message=f"WordPress.com site '{site_name}' detected. Connect your account for enhanced data or use HTML fallback.",
                        )
                    except Exception as e:
                        self.logger.log_error(
                            f"Failed to parse WordPress.com API response: {e}",
                            error_type="json_parse_error",
                            domain=domain
                        )
                
                elif status_code == 404:
                    self.logger.log_action(
                        "wordpress_com_public_api_probe",
                        "site_not_found",
                        domain=domain,
                        status_code=status_code
                    )
                
                else:
                    self.logger.log_action(
                        "wordpress_com_public_api_probe",
                        "unexpected_status",
                        domain=domain,
                        status_code=status_code
                    )
                
        except httpx.TimeoutException:
            self.logger.log_error(
                "Timeout while probing WordPress.com public API",
                error_type="timeout",
                domain=domain,
                api_url=public_api_url
            )
        except Exception as e:
            self.logger.log_error(
                f"Error probing WordPress.com public API: {e}",
                error_type="api_error",
                domain=domain
            )
        
        return None
    
    async def _is_wordpress_com(self, site_url: str, client: httpx.AsyncClient) -> bool:
        """Check if site is hosted on WordPress.com (HTML marker check)."""
        try:
            # Check for WordPress.com specific patterns
            response = await client.get(site_url)
            html = response.text.lower()
            
            # WordPress.com markers
            markers = [
                "wordpress.com",
                "wpcomcdn.com",
                "wp-content/plugins/jetpack",
                "stats.wp.com",
            ]
            
            return any(marker in html for marker in markers)
        except:
            return False
    
    async def _detect_shopify(self, site_url: str, page_url: str) -> CMSDetectionResult:
        """
        Detect Shopify stores.
        
        Strategy:
        1. Check for Shopify-specific headers
        2. Check for /products.json endpoint
        3. Check for CDN patterns (cdn.shopify.com)
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                # First check for Shopify headers
                response = await client.get(site_url)
                
                # Check headers
                server = response.headers.get("server", "").lower()
                powered_by = response.headers.get("x-powered-by", "").lower()
                
                if "shopify" in server or "shopify" in powered_by:
                    self.logger.log_http_probe(
                        url=page_url,
                        endpoint="headers",
                        status_code=response.status_code,
                        result="shopify_header_detected"
                    )
                    
                    self.logger.log_decision(
                        decision="shopify_detected",
                        reason="Shopify server header present",
                        url=page_url,
                        next_step="check_api_or_html_fallback"
                    )
                    
                    return CMSDetectionResult(
                        cms_type=CMSType.SHOPIFY,
                        rest_status=RESTStatus.NOT_FOUND,  # No API key configured
                        auth_required=AuthRequirement.NONE,
                        site_url=site_url,
                        confidence=0.9,
                        requires_oauth=False,
                        oauth_optional=False,
                        message="Shopify store detected. API credentials not configured - using HTML scraping.",
                    )
                
                # Check for Shopify CDN patterns in HTML
                html = response.text.lower()
                shopify_patterns = [
                    "cdn.shopify.com",
                    "shopify.com/s/",
                    "myshopify.com",
                    '"shopify"',
                ]
                
                if any(pattern in html for pattern in shopify_patterns):
                    self.logger.log_http_probe(
                        url=page_url,
                        endpoint="html_content",
                        status_code=response.status_code,
                        result="shopify_cdn_detected"
                    )
                    
                    self.logger.log_decision(
                        decision="shopify_detected",
                        reason="Shopify CDN patterns found in HTML",
                        url=page_url,
                        next_step="html_fallback"
                    )
                    
                    return CMSDetectionResult(
                        cms_type=CMSType.SHOPIFY,
                        rest_status=RESTStatus.NOT_FOUND,
                        auth_required=AuthRequirement.NONE,
                        site_url=site_url,
                        confidence=0.8,
                        requires_oauth=False,
                        oauth_optional=False,
                        message="Shopify store detected. Using HTML scraping (no API credentials).",
                    )
                
        except Exception as e:
            self.logger.log_error(
                f"Error while detecting Shopify: {str(e)}",
                error_type="detection_error",
                url=page_url
            )
        
        # Not Shopify
        return CMSDetectionResult(
            cms_type=CMSType.UNKNOWN,
            rest_status=RESTStatus.NOT_FOUND,
            auth_required=AuthRequirement.NONE,
            site_url=site_url,
            confidence=0.0,
            requires_oauth=False,
            oauth_optional=False,
            message="Shopify not detected.",
        )
    
    def _status_to_result(self, status_code: int) -> str:
        """Convert HTTP status to result string for logging."""
        if status_code == 200:
            return "success"
        elif status_code in [401, 403]:
            return "blocked"
        elif status_code == 404:
            return "not_found"
        else:
            return f"http_{status_code}"
