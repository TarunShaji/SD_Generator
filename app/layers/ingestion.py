"""
Ingestion Layer for the Structured Data Automation Tool.
This is Layer 3 - Source-agnostic content consumption.
"""
from typing import Optional

from app.models.content import NormalizedContent, SourceType
from app.layers.cms_detection import CMSDetectionResult, CMSType, RESTStatus, AuthRequirement
from app.adapters.html_scraper import HTMLScraper
from app.adapters.wordpress import WordPressAdapter
from app.adapters.shopify import ShopifyAdapter
from app.utils.logger import LayerLogger


class IngestionLayer:
    """
    Ingestion Layer - source-agnostic content consumption.
    
    This layer:
    - Consumes content without caring how it was fetched
    - Normalizes all inputs into one internal content model
    - Handles fallback logic transparently
    
    CMS type, auth method, and OAuth tokens are invisible here.
    """
    
    def __init__(self):
        self.logger = LayerLogger("ingestion_layer")
        self.html_scraper = HTMLScraper()
        self.wordpress_adapter = WordPressAdapter()
        self.shopify_adapter = ShopifyAdapter()
    
    async def ingest(
        self,
        url: str,
        cms_result: Optional[CMSDetectionResult] = None,
        force_html: bool = False,
        access_token: Optional[str] = None,
    ) -> NormalizedContent:
        """
        Ingest content from the appropriate source.
        
        Args:
            url: The page URL to ingest
            cms_result: CMS detection result (if available)
            force_html: Force HTML-only mode (user selected)
            access_token: OAuth access token (if available)
        
        Returns:
            NormalizedContent model
        """
        self.logger.log_action(
            "ingestion",
            "started",
            url=url,
            force_html=force_html,
            cms_type=cms_result.cms_type.value if cms_result else "not_detected"
        )
        
        # HTML-only mode - skip all CMS logic
        if force_html:
            self.logger.log_decision(
                decision="use_html_scraper",
                reason="HTML-only mode explicitly selected by user",
                url=url
            )
            return await self.html_scraper.fetch_and_parse(
                url, 
                reason="user_selected_html_mode"
            )
        
        # No CMS detection result - fall back to HTML
        if not cms_result:
            self.logger.log_fallback(
                from_source="cms_api",
                to_source="html_scraper",
                reason="No CMS detection result provided",
                url=url
            )
            return await self.html_scraper.fetch_and_parse(
                url,
                reason="no_cms_detection"
            )
        
        # Route based on CMS type
        try:
            content = await self._route_by_cms(url, cms_result, access_token)
            return content
        except Exception as e:
            # Fallback to HTML on any error
            self.logger.log_fallback(
                from_source=cms_result.cms_type.value,
                to_source="html_scraper",
                reason=f"CMS ingestion failed: {str(e)}",
                url=url
            )
            return await self.html_scraper.fetch_and_parse(
                url,
                reason=f"cms_error_fallback: {str(e)}"
            )
    
    async def _route_by_cms(
        self,
        url: str,
        cms_result: CMSDetectionResult,
        access_token: Optional[str],
    ) -> NormalizedContent:
        """Route to appropriate adapter based on CMS type."""
        
        # WordPress handling
        if cms_result.cms_type in [CMSType.WORDPRESS, CMSType.WORDPRESS_COM]:
            return await self._ingest_wordpress(url, cms_result, access_token)
        
        # Shopify handling
        elif cms_result.cms_type == CMSType.SHOPIFY:
            return await self._ingest_shopify(url, cms_result)
        
        # Unknown CMS - HTML fallback
        else:
            self.logger.log_decision(
                decision="use_html_scraper",
                reason="Unknown CMS type",
                url=url,
                cms_type=cms_result.cms_type.value
            )
            return await self.html_scraper.fetch_and_parse(
                url,
                reason="unknown_cms"
            )
    
    async def _ingest_wordpress(
        self,
        url: str,
        cms_result: CMSDetectionResult,
        access_token: Optional[str],
    ) -> NormalizedContent:
        """Ingest content from WordPress."""
        
        # Check if REST is available
        if cms_result.rest_status == RESTStatus.AVAILABLE:
            self.logger.log_decision(
                decision="use_wordpress_rest",
                reason="REST API available without authentication",
                url=url
            )
            
            return await self.wordpress_adapter.fetch_content(
                url=url,
                site_url=cms_result.site_url,
                authenticated=False
            )
        
        # REST blocked - check auth classification
        elif cms_result.rest_status == RESTStatus.BLOCKED:
            # Only use OAuth if auth_required is explicitly OAUTH
            if cms_result.auth_required == AuthRequirement.OAUTH and access_token:
                self.logger.log_decision(
                    decision="use_wordpress_rest_auth",
                    reason="REST blocked, auth_required=OAUTH, OAuth token available",
                    url=url,
                    auth_type="oauth"
                )
                
                self.wordpress_adapter.set_access_token(access_token)
                return await self.wordpress_adapter.fetch_content(
                    url=url,
                    site_url=cms_result.site_url,
                    authenticated=True
                )
            
            # auth_required is UNKNOWN - do NOT attempt OAuth, fall back to HTML
            elif cms_result.auth_required == AuthRequirement.UNKNOWN:
                self.logger.log_fallback(
                    from_source="wordpress_rest",
                    to_source="html_scraper",
                    reason="REST blocked, auth_required=UNKNOWN (self-hosted with unknown auth method)",
                    url=url
                )
                return await self.html_scraper.fetch_and_parse(
                    url,
                    reason="rest_blocked_auth_unknown"
                )
            
            # No token available for OAuth site
            else:
                self.logger.log_fallback(
                    from_source="wordpress_rest",
                    to_source="html_scraper",
                    reason="REST blocked and no OAuth token provided",
                    url=url
                )
                return await self.html_scraper.fetch_and_parse(
                    url,
                    reason="rest_blocked_no_oauth"
                )
        
        # REST not found or error - HTML fallback
        else:
            self.logger.log_fallback(
                from_source="wordpress_rest",
                to_source="html_scraper",
                reason=f"REST status: {cms_result.rest_status.value}",
                url=url
            )
            return await self.html_scraper.fetch_and_parse(
                url,
                reason=f"rest_{cms_result.rest_status.value}"
            )
    
    async def _ingest_shopify(
        self,
        url: str,
        cms_result: CMSDetectionResult,
    ) -> NormalizedContent:
        """Ingest content from Shopify."""
        
        # Check if Shopify API is configured
        if self.shopify_adapter.is_configured():
            self.logger.log_decision(
                decision="use_shopify_api",
                reason="Shopify API credentials available",
                url=url
            )
            
            try:
                return await self.shopify_adapter.fetch_content(
                    url=url,
                    shop_domain=cms_result.site_url
                )
            except NotImplementedError:
                # API not implemented yet - fallback
                pass
        
        # Fall back to HTML
        self.logger.log_fallback(
            from_source="shopify_api",
            to_source="html_scraper",
            reason="Shopify API not configured or not implemented",
            url=url
        )
        return await self.html_scraper.fetch_and_parse(
            url,
            reason="shopify_api_unavailable"
        )
