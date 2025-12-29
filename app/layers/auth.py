"""
Authentication Layer for the Structured Data Automation Tool.
This is Layer 2 - OPTIONAL, handles OAuth for WordPress.com only.
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlencode

from app.utils.logger import LayerLogger
from app.config import config


class OAuthStatus(str, Enum):
    """OAuth flow status."""
    NOT_STARTED = "not_started"
    REDIRECT_INITIATED = "redirect_initiated"
    AUTHORIZED = "authorized"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"


@dataclass
class OAuthState:
    """OAuth state for tracking the flow."""
    status: OAuthStatus
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    error: Optional[str] = None
    site_url: Optional[str] = None


class AuthenticationLayer:
    """
    Authentication Layer - handles OAuth for WordPress.com.
    
    IMPORTANT RULES:
    - This layer is FULLY OPTIONAL
    - Never triggered automatically
    - Only activated when:
      1. CMS Detection returns auth_required == OAUTH
      2. User explicitly clicks "Connect CMS"
    
    NEVER activated for:
    - auth_required == UNKNOWN (self-hosted WP with blocked REST)
    - auth_required == BASIC (not implemented)
    - auth_required == APPLICATION_PASSWORD (not implemented)
    
    - Tokens never leak outside this layer
    """
    
    # WordPress.com OAuth endpoints
    WP_AUTHORIZE_URL = "https://public-api.wordpress.com/oauth2/authorize"
    WP_TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"
    
    def __init__(self):
        self.logger = LayerLogger("auth_layer")
        self._oauth_states: Dict[str, OAuthState] = {}  # session_id -> state
    
    def is_configured(self) -> bool:
        """Check if OAuth is configured with credentials."""
        configured = config.is_wp_oauth_configured()
        
        if not configured:
            missing_vars = config.get_missing_oauth_vars()
            self.logger.log_decision(
                decision="oauth_not_configured",
                reason="missing_client_credentials",
                missing_variables=missing_vars
            )
        
        return configured
    
    def get_authorization_url(self, session_id: str, site_url: str) -> str:
        """
        Generate WordPress.com OAuth authorization URL.
        
        Args:
            session_id: Unique session identifier for state tracking
            site_url: The WordPress.com site URL
        
        Returns:
            Authorization URL to redirect user to
        """
        if not self.is_configured():
            missing_vars = config.get_missing_oauth_vars()
            self.logger.log_error(
                "Cannot generate auth URL - OAuth not configured",
                error_type="configuration_error",
                missing_variables=missing_vars
            )
            raise ValueError(f"OAuth is not configured. Missing: {', '.join(missing_vars)}")
        
        self.logger.log_action(
            "oauth_initiate",
            "started",
            session_id=session_id,
            site_url=site_url,
            redirect_uri=config.WP_OAUTH_REDIRECT_URI
        )
        
        # Redirect URI safety check (log-only, don't block)
        expected_callback = "/api/oauth/wordpress/callback"
        if config.WP_OAUTH_REDIRECT_URI and expected_callback not in config.WP_OAUTH_REDIRECT_URI:
            self.logger.info(
                "redirect_uri_mismatch_warning",
                message="Redirect URI may not match expected callback path",
                expected_contains=expected_callback,
                configured_uri=config.WP_OAUTH_REDIRECT_URI
            )
        
        # Store OAuth state
        self._oauth_states[session_id] = OAuthState(
            status=OAuthStatus.REDIRECT_INITIATED,
            site_url=site_url
        )
        
        # Build authorization URL
        params = {
            "client_id": config.WP_OAUTH_CLIENT_ID,
            "redirect_uri": config.WP_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "global",  # Read access to all sites
            "state": session_id,  # For CSRF protection
        }
        
        if site_url:
            params["blog"] = site_url
        
        auth_url = f"{self.WP_AUTHORIZE_URL}?{urlencode(params)}"
        
        self.logger.log_action(
            "oauth_redirect_prepared",
            "completed",
            session_id=session_id,
            redirect_initiated=True,
            authorize_url_generated=True
        )
        
        return auth_url
    
    async def handle_callback(
        self, 
        code: str, 
        state: str
    ) -> OAuthState:
        """
        Handle OAuth callback from WordPress.com.
        
        Args:
            code: Authorization code from WordPress
            state: State parameter (session_id)
        
        Returns:
            OAuthState with access token or error
        """
        import httpx
        
        self.logger.log_action(
            "oauth_callback",
            "started",
            session_id=state,
            code_received=bool(code)
        )
        
        # Validate state
        if state not in self._oauth_states:
            self.logger.log_error(
                "Invalid OAuth state - possible CSRF attempt",
                error_type="security_error",
                session_id=state
            )
            return OAuthState(
                status=OAuthStatus.FAILED,
                error="Invalid state parameter"
            )
        
        if not self.is_configured():
            return OAuthState(
                status=OAuthStatus.NOT_CONFIGURED,
                error="OAuth not configured"
            )
        
        # Exchange code for token
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self.WP_TOKEN_URL,
                    data={
                        "client_id": config.WP_OAUTH_CLIENT_ID,
                        "client_secret": config.WP_OAUTH_CLIENT_SECRET,
                        "code": code,
                        "redirect_uri": config.WP_OAUTH_REDIRECT_URI,
                        "grant_type": "authorization_code",
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    oauth_state = OAuthState(
                        status=OAuthStatus.AUTHORIZED,
                        access_token=data.get("access_token"),
                        site_url=self._oauth_states[state].site_url
                    )
                    
                    self._oauth_states[state] = oauth_state
                    
                    self.logger.log_action(
                        "oauth_token_exchange",
                        "completed",
                        session_id=state,
                        success=True
                    )
                    
                    return oauth_state
                else:
                    error_msg = response.text
                    
                    self.logger.log_error(
                        f"Token exchange failed: {error_msg}",
                        error_type="oauth_error",
                        session_id=state,
                        status_code=response.status_code
                    )
                    
                    return OAuthState(
                        status=OAuthStatus.FAILED,
                        error=f"Token exchange failed: {response.status_code}"
                    )
                    
        except Exception as e:
            self.logger.log_error(
                f"OAuth callback error: {str(e)}",
                error_type="oauth_error",
                session_id=state
            )
            
            return OAuthState(
                status=OAuthStatus.FAILED,
                error=str(e)
            )
    
    def get_access_token(self, session_id: str) -> Optional[str]:
        """
        Get access token for a session.
        
        Args:
            session_id: Session identifier
        
        Returns:
            Access token if authorized, None otherwise
        """
        state = self._oauth_states.get(session_id)
        
        if state and state.status == OAuthStatus.AUTHORIZED:
            return state.access_token
        
        return None
    
    def clear_session(self, session_id: str):
        """Clear OAuth state for a session."""
        if session_id in self._oauth_states:
            del self._oauth_states[session_id]
            self.logger.log_action(
                "oauth_session_cleared",
                "completed",
                session_id=session_id
            )
