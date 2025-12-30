"""
Structured Data Automation Tool - FastAPI Application
Main entry point with REST API endpoints.
"""
import json
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from app.config import config
from app.utils.logger import get_logger, set_trace_id
from app.layers.cms_detection import CMSDetectionLayer, CMSType
from app.layers.auth import AuthenticationLayer
from app.layers.ingestion import IngestionLayer
from app.layers.ai_enhancement import AIEnhancementLayer
from app.generators.schema_generator import SchemaGenerator


# Initialize FastAPI app
app = FastAPI(
    title="Structured Data Automation Tool",
    description="SEO tool that automatically generates schema.org JSON-LD structured data",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize layers
cms_detector = CMSDetectionLayer()
auth_layer = AuthenticationLayer()
ingestion_layer = IngestionLayer()
ai_enhancement_layer = AIEnhancementLayer()
schema_generator = SchemaGenerator()

logger = get_logger("main")


# Request/Response models
class GenerateRequest(BaseModel):
    """Request model for schema generation."""
    url: str
    mode: str = "cms"  # "cms" or "html"
    cms_type: Optional[str] = None  # "wordpress" or "shopify"
    ai_enhance: bool = False  # Enable AI-powered enhancements


class GenerateResponse(BaseModel):
    """Response model for schema generation."""
    url: str
    mode: str
    cms_detected: Optional[str]
    source_used: str
    content_type: str
    confidence: float
    schemas: list
    script_tag: str
    trace_id: str
    ai_enhanced: bool = False
    ai_enhancements: Optional[list] = None


class CMSDetectionResponse(BaseModel):
    """Response model for CMS detection."""
    url: str
    cms_type: str
    rest_status: str
    auth_required: str  # NEW: Authentication requirement classification
    confidence: float
    requires_oauth: bool
    oauth_optional: bool
    message: str
    trace_id: str


# API Routes
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/detect-cms")
async def detect_cms(url: str = Query(..., description="URL to detect CMS for")):
    """
    Detect CMS type for a given URL.
    
    Returns CMS type, REST availability, and OAuth requirements.
    """
    trace_id = set_trace_id()
    
    logger.info("cms_detection_request", url=url, trace_id=trace_id)
    
    try:
        result = await cms_detector.detect(url)
        
        return CMSDetectionResponse(
            url=url,
            cms_type=result.cms_type.value,
            rest_status=result.rest_status.value,
            auth_required=result.auth_required.value,
            confidence=result.confidence,
            requires_oauth=result.requires_oauth,
            oauth_optional=result.oauth_optional,
            message=result.message,
            trace_id=trace_id,
        )
    except Exception as e:
        logger.error("cms_detection_error", error=str(e), url=url)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate")
async def generate_schema(request: GenerateRequest):
    """
    Generate structured data for a URL.
    
    Supports two modes:
    - cms: CMS-based mode with REST API preference
    - html: HTML-only mode (direct scraping)
    """
    trace_id = set_trace_id()
    
    logger.info(
        "schema_generation_request",
        url=request.url,
        mode=request.mode,
        cms_type=request.cms_type,
        ai_enhance=request.ai_enhance,
        trace_id=trace_id
    )
    
    try:
        # Handle AI mode: treat as HTML + ai_enhance
        is_ai_mode = request.mode == "ai"
        effective_mode = "html" if is_ai_mode else request.mode
        ai_enhance = request.ai_enhance or is_ai_mode
        
        logger.info(
            "mode_resolved",
            original_mode=request.mode,
            effective_mode=effective_mode,
            ai_enhance=ai_enhance
        )
        
        force_html = effective_mode == "html"
        cms_result = None
        
        # Detect CMS if in CMS mode
        if not force_html:
            cms_result = await cms_detector.detect(request.url)
        
        # Ingest content
        content = await ingestion_layer.ingest(
            url=request.url,
            cms_result=cms_result,
            force_html=force_html,
        )
        
        # Apply AI enhancements if requested
        ai_report = None
        if ai_enhance and ai_enhancement_layer.is_available():
            logger.info("ai_enhancement_starting", url=request.url)
            content, ai_report = await ai_enhancement_layer.enhance_content(
                content=content,
                body_text=content.body
            )
            logger.info(
                "ai_enhancement_applied",
                ai_enhanced=ai_report.ai_enhanced,
                enhancements_count=len([e for e in ai_report.enhancements if e.success])
            )
        
        # Generate schemas
        schema_collection = schema_generator.generate(content)
        
        # Log normalized content to terminal for debugging
        logger.info(
            "normalized_content_extracted",
            url=content.url,
            title=content.title,
            description=content.description[:200] if content.description else None,
            body_length=len(content.body) if content.body else 0,
            headings_count=len(content.headings),
            images_count=len(content.images),
            faq_count=len(content.faq),
            breadcrumbs_count=len(content.breadcrumbs),
            content_type=content.content_type.value,
            source_type=content.source_type.value,
            confidence_score=content.confidence_score,
            author=content.author,
            published_date=content.published_date,
            organization_name=content.organization_name,
        )
        
        # Log headings for debugging
        if content.headings:
            logger.info(
                "extracted_headings",
                headings=[{"level": h.level, "text": h.text} for h in content.headings[:10]]
            )
        
        # Log FAQ if present
        if content.faq:
            logger.info(
                "extracted_faq",
                faq=[{"question": f.question, "answer": f.answer[:100]} for f in content.faq]
            )
        
        # Log product-specific data if present
        if content.product_offer:
            logger.info(
                "extracted_product_offer",
                price=content.product_offer.price,
                currency=content.product_offer.currency,
                availability=content.product_offer.availability
            )
        
        if content.product_rating:
            logger.info(
                "extracted_product_rating",
                rating_value=content.product_rating.rating_value,
                review_count=content.product_rating.review_count
            )
        
        if content.product_variants:
            logger.info(
                "extracted_product_variants",
                variants_count=len(content.product_variants),
                variants=[{"name": v.name, "price": v.price} for v in content.product_variants[:5]]
            )
        
        # Log generated schema types
        logger.info(
            "schemas_generated",
            schema_types=[s.get("@type") for s in schema_collection.schemas],
            schemas_count=len(schema_collection.schemas)
        )
        
        return GenerateResponse(
            url=request.url,
            mode=request.mode,
            cms_detected=cms_result.cms_type.value if cms_result else None,
            source_used=content.source_type.value,
            content_type=content.content_type.value,
            confidence=content.confidence_score,
            schemas=schema_collection.schemas,
            script_tag=schema_collection.to_script_tag(),
            trace_id=trace_id,
            ai_enhanced=ai_report.ai_enhanced if ai_report else False,
            ai_enhancements=ai_report.to_dict()["enhancements"] if ai_report else None,
        )
        
    except Exception as e:
        logger.error("schema_generation_error", error=str(e), url=request.url)
        raise HTTPException(status_code=500, detail=str(e))


# OAuth Routes (WordPress.com)
@app.get("/api/oauth/wordpress/initiate")
async def initiate_wordpress_oauth(
    url: str = Query(..., description="WordPress.com site URL"),
    session_id: Optional[str] = Query(None, description="Session identifier")
):
    """
    Initiate OAuth flow for WordPress.com.
    
    This is OPTIONAL and only triggered by explicit user action.
    """
    if not auth_layer.is_configured():
        raise HTTPException(
            status_code=400,
            detail="WordPress OAuth is not configured. Set WP_OAUTH_CLIENT_ID and WP_OAUTH_CLIENT_SECRET."
        )
    
    session_id = session_id or str(uuid.uuid4())
    
    try:
        auth_url = auth_layer.get_authorization_url(session_id, url)
        return {
            "session_id": session_id,
            "authorization_url": auth_url,
            "message": "Redirect user to authorization_url to complete OAuth"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/oauth/wordpress/callback")
async def wordpress_oauth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter (session_id)")
):
    """
    Handle OAuth callback from WordPress.com.
    
    Exchanges authorization code for access token.
    """
    trace_id = set_trace_id()
    
    try:
        oauth_state = await auth_layer.handle_callback(code, state)
        
        if oauth_state.status.value == "authorized":
            # Return success page
            return HTMLResponse(content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Authorization Successful</title>
                    <style>
                        body {{ font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }}
                        .container {{ text-align: center; padding: 40px; background: rgba(255,255,255,0.1); border-radius: 16px; }}
                        h1 {{ color: #4ade80; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>✓ Authorization Successful</h1>
                        <p>You can close this window and return to the app.</p>
                        <p>Session ID: {state}</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                session_id: '{state}'
                            }}, '*');
                        }}
                    </script>
                </body>
                </html>
            """)
        else:
            return HTMLResponse(content=f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Authorization Failed</title>
                    <style>
                        body {{ font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: #eee; }}
                        .container {{ text-align: center; padding: 40px; background: rgba(255,255,255,0.1); border-radius: 16px; }}
                        h1 {{ color: #ef4444; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>✗ Authorization Failed</h1>
                        <p>{oauth_state.error or 'Unknown error'}</p>
                    </div>
                </body>
                </html>
            """, status_code=400)
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Serve static files and frontend
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the frontend UI."""
    try:
        with open("app/static/index.html", "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Frontend not found. Please create app/static/index.html</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
