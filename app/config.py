"""
Configuration management for Structured Data Automation Tool.
Handles environment variables and application settings.
"""
import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""
    
    # Server settings
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # WordPress OAuth (optional - only for WordPress.com)
    # These are loaded from environment variables, NEVER hardcoded
    WP_OAUTH_CLIENT_ID: Optional[str] = os.getenv("WP_OAUTH_CLIENT_ID")
    WP_OAUTH_CLIENT_SECRET: Optional[str] = os.getenv("WP_OAUTH_CLIENT_SECRET")
    WP_OAUTH_REDIRECT_URI: Optional[str] = os.getenv("WP_OAUTH_REDIRECT_URI")
    
    # Shopify API (optional - stubbed for v1)
    SHOPIFY_API_KEY: Optional[str] = os.getenv("SHOPIFY_API_KEY")
    SHOPIFY_API_SECRET: Optional[str] = os.getenv("SHOPIFY_API_SECRET")
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")  # json or console
    
    # Request settings
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))
    
    @classmethod
    def is_wp_oauth_configured(cls) -> bool:
        """
        Check if WordPress OAuth credentials are fully configured.
        
        Requires ALL of:
        - WP_OAUTH_CLIENT_ID
        - WP_OAUTH_CLIENT_SECRET
        - WP_OAUTH_REDIRECT_URI
        """
        return all([
            cls.WP_OAUTH_CLIENT_ID,
            cls.WP_OAUTH_CLIENT_SECRET,
            cls.WP_OAUTH_REDIRECT_URI
        ])
    
    @classmethod
    def get_missing_oauth_vars(cls) -> list:
        """Return list of missing OAuth environment variables."""
        missing = []
        if not cls.WP_OAUTH_CLIENT_ID:
            missing.append("WP_OAUTH_CLIENT_ID")
        if not cls.WP_OAUTH_CLIENT_SECRET:
            missing.append("WP_OAUTH_CLIENT_SECRET")
        if not cls.WP_OAUTH_REDIRECT_URI:
            missing.append("WP_OAUTH_REDIRECT_URI")
        return missing
    
    @classmethod
    def is_shopify_configured(cls) -> bool:
        """Check if Shopify API credentials are configured."""
        return bool(cls.SHOPIFY_API_KEY and cls.SHOPIFY_API_SECRET)


config = Config()
