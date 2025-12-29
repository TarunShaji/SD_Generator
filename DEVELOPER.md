# 🛠️ Developer Reference Guide

> Internal technical documentation explaining how the Structured Data Automation Tool works.

---

## Table of Contents

- [Quick Architecture Overview](#quick-architecture-overview)
- [Directory Structure](#directory-structure)
- [Core Modules Explained](#core-modules-explained)
- [Data Flow Walkthrough](#data-flow-walkthrough)
- [Key Classes and Functions](#key-classes-and-functions)
- [How To Extend](#how-to-extend)

---

## Quick Architecture Overview

```
User Request → FastAPI → CMS Detection → Auth (optional) → Ingestion → Schema Generator → JSON-LD
```

**Three Layers**:
1. **CMS Detection** - Figures out what CMS the site uses (WordPress, Shopify, Unknown)
2. **Auth Layer** - Handles OAuth for WordPress.com (only if user clicks "Connect")
3. **Ingestion Layer** - Fetches content via REST API or HTML scraping

**Three Adapters**:
1. **WordPress Adapter** - Talks to `/wp-json/wp/v2/` endpoints
2. **Shopify Adapter** - Stubbed for future; always falls back to HTML
3. **HTML Scraper** - BeautifulSoup-based fallback for any site

**One Output**:
- Everything gets normalized into `NormalizedContent` → fed to `SchemaGenerator` → outputs JSON-LD

---

## Directory Structure

```
app/
├── main.py              # FastAPI entry point, all routes defined here
├── config.py            # Environment variables and settings
│
├── models/              # Data structures (Pydantic models)
│   ├── content.py       # NormalizedContent - the universal content format
│   └── schema.py        # JSON-LD schema models (Article, FAQPage, etc.)
│
├── layers/              # The three-layer architecture
│   ├── cms_detection.py # Layer 1: Detect WordPress/Shopify/Unknown
│   ├── auth.py          # Layer 2: OAuth for WordPress.com (optional)
│   └── ingestion.py     # Layer 3: Route to correct adapter
│
├── adapters/            # Data fetchers (one per source type)
│   ├── wordpress.py     # WordPress REST API client
│   ├── shopify.py       # Shopify API client (stubbed)
│   └── html_scraper.py  # BeautifulSoup HTML parser
│
├── generators/          # Output generators
│   └── schema_generator.py  # Converts NormalizedContent → JSON-LD
│
├── utils/               # Utilities
│   └── logger.py        # Structured logging with trace IDs
│
└── static/              # Frontend files
    ├── index.html       # Single-page UI
    ├── style.css        # Dark theme styles
    └── app.js           # Frontend JavaScript logic
```

---

## Core Modules Explained

### `app/main.py` - The Entry Point

**What it does**: Defines all API routes and starts the FastAPI server.

**Key Routes**:
| Route | Method | What it does |
|-------|--------|--------------|
| `/api/health` | GET | Returns `{"status": "healthy"}` |
| `/api/detect-cms` | GET | Runs CMS detection on a URL |
| `/api/generate` | POST | Main endpoint - generates schema from URL |
| `/api/oauth/wordpress/initiate` | GET | Starts OAuth flow (user-triggered) |
| `/api/oauth/wordpress/callback` | GET | Handles OAuth callback |
| `/` | GET | Serves the frontend UI |

**How requests flow**:
```python
# Simplified flow in /api/generate endpoint:
1. Set trace ID for logging
2. If mode == "html": skip CMS detection
3. If mode == "cms": run cms_detector.detect(url)
4. Pass result to ingestion_layer.ingest(url, cms_result)
5. Pass content to schema_generator.generate(content)
6. Return JSON-LD
```

---

### `app/config.py` - Configuration

**What it does**: Loads environment variables and provides typed access.

**Key Settings**:
```python
config.WP_OAUTH_CLIENT_ID      # WordPress OAuth client ID
config.WP_OAUTH_CLIENT_SECRET  # WordPress OAuth secret
config.LOG_LEVEL               # INFO, DEBUG, etc.
config.REQUEST_TIMEOUT         # HTTP timeout in seconds
```

**Helper Methods**:
```python
config.is_wp_oauth_configured()  # Returns True if OAuth credentials set
config.is_shopify_configured()   # Returns True if Shopify API keys set
```

---

### `app/models/content.py` - The Universal Content Model

**What it does**: Defines `NormalizedContent` - the single data structure that all adapters output.

**Why it matters**: Whether data comes from WordPress REST, Shopify API, or HTML scraping, it all gets converted to this format. The schema generator only knows about this model.

**Key Fields**:
```python
class NormalizedContent:
    url: str                    # The page URL
    title: str                  # Page title
    description: str            # Meta description
    body: str                   # Main content text (max 5000 chars)
    headings: List[HeadingData] # H1-H6 with level and text
    images: List[ImageData]     # Images with src, alt, dimensions
    faq: List[FAQItem]          # Question/answer pairs
    breadcrumbs: List[BreadcrumbItem]
    content_type: ContentType   # ARTICLE, BLOG_POST, SERVICE, etc.
    source_type: SourceType     # WORDPRESS_REST, HTML_SCRAPER, etc.
    confidence_score: float     # 0.0-1.0, how complete the extraction was
    
    # Product-specific fields
    product_sku: Optional[str]             # Product SKU
    product_mpn: Optional[str]             # Manufacturer Part Number (NEW)
    product_brand: Optional[str]           # Brand name
    product_offer: Optional[ProductOffer]  # Price, currency, availability
    product_rating: Optional[AggregateRatingData]  # Rating and reviews
    product_variants: List[ProductVariant] # Variant options
    product_images: List[str]              # JSON-LD images (NEW)
    delivery_info: Optional[str]           # Shipping/delivery text
    
    # Capability flags (computed from extracted data)
    capabilities: Optional[ProductCapabilities]
```

**ProductCapabilities Model** (NEW):
```python
class ProductCapabilities:
    has_price: bool           # product_offer.price exists
    has_currency: bool        # product_offer.currency exists
    has_availability: bool    # product_offer.availability exists
    has_rating: bool          # product_rating.rating_value exists
    has_reviews: bool         # product_rating.review_count > 0
    has_variants: bool        # len(product_variants) > 0
    has_delivery_info: bool   # delivery_info exists
    has_sku: bool             # product_sku exists
    has_brand: bool           # product_brand exists
    has_mpn: bool             # product_mpn exists (NEW)
    has_product_images: bool  # len(product_images) > 0 (NEW)
```

**Product-Related Models**:
```python
class ProductOffer:
    price: str              # e.g., "29.99"
    currency: str           # e.g., "USD"
    availability: str       # InStock, OutOfStock, PreOrder, LimitedAvailability

class AggregateRatingData:
    rating_value: float     # 0.0-5.0
    review_count: int       # Number of reviews

class ProductVariant:
    name: str               # e.g., "Large"
    value: str
    price: Optional[str]
    sku: Optional[str]
    available: bool
```

---

### `app/layers/cms_detection.py` - Layer 1

**What it does**: Probes a URL to determine what CMS it's running.

**Key Class**: `CMSDetectionLayer`

**Detection Logic**:
```python
# WordPress detection:
response = GET /wp-json/
if 200: WordPress, REST available, auth_required=NONE
if 401/403: WordPress, REST blocked → classify auth requirement
if 404: Not WordPress

# Auth Classification (NEW):
if is_wordpress_com(site_url):
    auth_required = OAUTH  # Offer "Connect WordPress.com"
else:
    auth_required = UNKNOWN  # Fall back to HTML, no OAuth prompt

# Shopify detection:
Check for "cdn.shopify.com" in HTML
Check for Shopify headers (X-Powered-By, Server)
```

**AuthRequirement Enum** (NEW):
```python
class AuthRequirement(Enum):
    NONE = "none"                  # No auth required (200 OK)
    OAUTH = "oauth"                # WordPress.com OAuth
    BASIC = "basic"                # Basic Auth (not implemented)
    APPLICATION_PASSWORD = "application_password"  # WP App Passwords (not implemented)
    UNKNOWN = "unknown"            # Blocked but cannot determine method
```

**Output**: `CMSDetectionResult` dataclass with:
- `cms_type`: WORDPRESS, WORDPRESS_COM, SHOPIFY, UNKNOWN
- `rest_status`: AVAILABLE, BLOCKED, NOT_FOUND
- `auth_required`: NONE, OAUTH, UNKNOWN (NEW)
- `oauth_optional`: True if OAuth can be offered
- `confidence`: 0.0-1.0

---

### `app/layers/auth.py` - Layer 2 (Optional)

**What it does**: Handles WordPress.com OAuth flow.

**Key Class**: `AuthenticationLayer`

**IMPORTANT RULES**:
- This layer is FULLY OPTIONAL
- NEVER auto-triggered
- Only activated when:
  1. CMS Detection returns `auth_required == OAUTH`
  2. User explicitly clicks "Connect CMS"

**NEVER activated for**:
- `auth_required == UNKNOWN` (self-hosted WP with blocked REST)
- `auth_required == BASIC` (not implemented)
- `auth_required == APPLICATION_PASSWORD` (not implemented)

**OAuth Flow**:
```python
1. is_configured() → Check if WP_OAUTH_CLIENT_ID, WP_OAUTH_CLIENT_SECRET, WP_OAUTH_REDIRECT_URI are set
2. get_authorization_url(session_id) → Returns WordPress.com auth URL
3. User is redirected, authorizes app
4. WordPress.com redirects to callback with code
5. handle_callback(code, state) → Exchanges code for access token
6. get_access_token(session_id) → Returns stored token for API calls
```

---

### `app/layers/ingestion.py` - Layer 3

**What it does**: Routes the request to the correct adapter based on CMS detection.

**Key Class**: `IngestionLayer`

**Routing Logic** (with Auth Classification):
```python
if force_html:
    → HTML Scraper

if WordPress + REST available (auth_required=NONE):
    → WordPress Adapter (no auth)

if WordPress + REST blocked + auth_required=OAUTH + has token:
    → WordPress Adapter (with OAuth)

if WordPress + REST blocked + auth_required=UNKNOWN:
    → HTML Scraper (no OAuth prompt, classified as unknown auth)

if WordPress + REST blocked + auth_required=OAUTH + no token:
    → HTML Scraper (fallback until user authenticates)

if Shopify:
    → HTML Scraper (API not implemented in v1)

if Unknown:
    → HTML Scraper
```

**Key Rule**: OAuth is ONLY used when `auth_required == OAUTH`. Self-hosted WordPress with blocked REST (`auth_required == UNKNOWN`) goes directly to HTML fallback.

**Output**: Always returns `NormalizedContent`

---

### `app/adapters/html_scraper.py` - The Fallback

**What it does**: Fetches HTML and extracts structured data using BeautifulSoup.

**Key Class**: `HTMLScraper`

**Extraction Methods**:
```python
_extract_title()              # og:title → <title> → H1
_extract_meta_description()
_extract_body_text()          # Removes nav/header/footer, gets main content
_extract_headings()           # All H1-H6 with level
_extract_images()             # src, alt, dimensions
_extract_faq()                # Looks for dt/dd pairs, question headings
_extract_breadcrumbs()        # aria-label="breadcrumb" or .breadcrumb class
_detect_content_type()        # URL patterns, schema already on page
_extract_script_json_data()   # NEW: Parses embedded JSON from <script> tags
```

---

### Product Data Extraction (Three-Layer Architecture)

**What it does**: Extracts product data from multiple sources using independent layers, then merges using trust-based precedence.

**Three Independent Layers**:

| Layer | Trust Level | Source | Data Extracted |
|-------|-------------|--------|----------------|
| **Layer 1: Visible DOM** | 0.6 (lowest) | HTML elements | Price, availability, variants, delivery text |
| **Layer 2: JSON-LD** | 0.9 (highest) | `<script type="application/ld+json">` | SKU, MPN, brand, offers, rating, images |
| **Layer 3: JS State** | 0.8 (medium) | `<script>` with JS objects | variants, product objects, analytics |

**Trust-Based Merge** (JSON-LD wins for most fields):

| Field | Priority Order |
|-------|----------------|
| `price/offers` | JSON-LD > JS State > DOM |
| `availability` | JSON-LD > JS State > DOM |
| `images` | JSON-LD > DOM |
| `rating` | JSON-LD > JS State > DOM |
| `variants` | JS State > DOM |
| `sku/mpn/brand` | JSON-LD > JS State > DOM |
| `delivery_text` | DOM only |

**Key Methods**:
```python
_extract_script_json_data()     # Main entry point
_extract_from_visible_dom()     # Layer 1: DOM extraction
_extract_from_jsonld_layer()    # Layer 2: JSON-LD extraction
_extract_from_js_state_layer()  # Layer 3: JS state extraction
_trust_based_merge()            # Merge with field-specific precedence
_parse_jsonld_product()         # Parse Product from JSON-LD
_normalize_jsonld_images()      # Handle image arrays
_parse_offer()                  # Convert to ProductOffer
_parse_rating()                 # Convert to AggregateRatingData
```

**@graph Handling**:
- JSON-LD `@graph` arrays are fully iterated
- All `Product`, `BreadcrumbList`, and other types extracted
- No early returns on first match

**Terminal Logs**:
```json
{"event": "product_extraction", "sources": [["dom", ["product_offer"]], ["jsonld", ["sku", "product_offer", "product_images"]]]}
{"event": "trust_based_merge", "decisions": [{"field": "product_offer", "source": "jsonld"}, {"field": "product_images", "source": "jsonld", "count": 5}]}
{"event": "breadcrumb_extraction", "status": "found_in_graph", "count": 3}
```

---

### `app/adapters/wordpress.py` - WordPress REST Client

**What it does**: Fetches content from WordPress REST API.

**Key Class**: `WordPressAdapter`

**How it works**:
```python
1. Extract slug from URL (/blog/my-post → "my-post")
2. Try GET /wp-json/wp/v2/posts?slug=my-post
3. If not found, try GET /wp-json/wp/v2/pages?slug=my-post
4. Parse response and convert to NormalizedContent
```

**Auth Mode**:
```python
adapter.set_access_token(token)  # Store OAuth token
adapter.fetch_content(url, authenticated=True)  # Uses Bearer token
```

---

### `app/adapters/shopify.py` - Stubbed for Future

**What it does**: Placeholder for Shopify API integration.

**Current Behavior**: Always raises `NotImplementedError`, which triggers HTML fallback.

**Future Implementation** (when API keys available):
```python
# GraphQL query for product
query {
  productByHandle(handle: "product-slug") {
    title
    description
    images { edges { node { url altText } } }
  }
}
```

---

### `app/generators/schema_generator.py` - The Output Generator

**What it does**: Converts `NormalizedContent` into JSON-LD schemas.

**Key Class**: `SchemaGenerator`

**Logic Flow**:
```python
1. generate(content) called
2. Generate primary schema based on content_type:
   - BLOG_POST → BlogPostingSchema
   - ARTICLE → ArticleSchema
   - SERVICE → ServiceSchema
   - PRODUCT → ProductSchema (with Offer + AggregateRating if available)
3. If FAQ data present (≥2 items) → Add FAQPageSchema
4. If breadcrumbs present (≥2 items) → Add BreadcrumbListSchema
5. If organization name present → Add OrganizationSchema
6. Return SchemaCollection
```

**Product Schema Generation** (enhanced):
```python
def _generate_product(content):
    # Build offers if price data exists
    if content.product_offer:
        offers = {
            "@type": "Offer",
            "price": content.product_offer.price,
            "priceCurrency": content.product_offer.currency,
            "availability": f"https://schema.org/{content.product_offer.availability}"
        }
    
    # Build aggregateRating if rating data exists
    if content.product_rating:
        aggregateRating = {
            "@type": "AggregateRating",
            "ratingValue": content.product_rating.rating_value,
            "reviewCount": content.product_rating.review_count
        }
    
    return ProductSchema(
        name=content.title,
        offers=offers,
        aggregateRating=aggregateRating,
        sku=content.product_sku,
        brand=brand_dict
    ).to_jsonld()
```

**Deterministic Rules**:
- Only outputs fields that have actual data
- Never infers or fabricates values
- Truncates long text (headline: 110 chars, description: 300 chars)

---

### `app/utils/logger.py` - Structured Logging

**What it does**: Provides JSON-formatted logs with trace IDs.

**Key Components**:
```python
get_trace_id()     # Get current request's trace ID
set_trace_id()     # Set new trace ID (called at request start)
get_logger(name)   # Get a structlog logger
LayerLogger(name)  # Specialized logger for layers
```

**LayerLogger Methods**:
```python
logger.log_decision(decision, reason, url)
logger.log_action(action, status)
logger.log_fallback(from_source, to_source, reason)
logger.log_error(error, error_type)
logger.log_http_probe(url, endpoint, status_code, result)
logger.log_normalization(source, fields_present, fields_missing, confidence)
```

---

## Data Flow Walkthrough

**Example**: User submits `https://myblog.wordpress.org/hello-world/` in CMS mode.

```
1. POST /api/generate
   Body: {"url": "https://myblog.wordpress.org/hello-world/", "mode": "cms"}

2. main.py sets trace_id = "a1b2c3d4"

3. cms_detector.detect(url) runs:
   - Probes /wp-json/ → 200 OK
   - Returns CMSDetectionResult(cms_type=WORDPRESS, rest_status=AVAILABLE)

4. ingestion_layer.ingest(url, cms_result) runs:
   - Sees WordPress + REST available
   - Calls wordpress_adapter.fetch_content(url)
   - WordPress adapter calls /wp-json/wp/v2/posts?slug=hello-world
   - Normalizes response into NormalizedContent

5. schema_generator.generate(content) runs:
   - content_type is BLOG_POST → creates BlogPostingSchema
   - No FAQ detected
   - No breadcrumbs in API response
   - Returns SchemaCollection with 1 schema

6. Response returned:
   {
     "url": "...",
     "source_used": "wordpress_rest",
     "content_type": "blog_post",
     "confidence": 0.9,
     "schemas": [{"@type": "BlogPosting", ...}],
     "script_tag": "<script type=\"application/ld+json\">...",
     "trace_id": "a1b2c3d4"
   }
```

---

## Key Classes and Functions

| Class/Function | File | Purpose |
|---------------|------|---------|
| `CMSDetectionLayer.detect()` | layers/cms_detection.py | Detect CMS type |
| `AuthenticationLayer.get_authorization_url()` | layers/auth.py | Start OAuth |
| `AuthenticationLayer.handle_callback()` | layers/auth.py | Complete OAuth |
| `IngestionLayer.ingest()` | layers/ingestion.py | Route to adapter |
| `HTMLScraper.fetch_and_parse()` | adapters/html_scraper.py | Scrape HTML |
| `WordPressAdapter.fetch_content()` | adapters/wordpress.py | Call WP REST |
| `SchemaGenerator.generate()` | generators/schema_generator.py | Create JSON-LD |
| `NormalizedContent` | models/content.py | Universal content model |
| `SchemaCollection.to_jsonld()` | models/schema.py | Convert to output |
| `LayerLogger` | utils/logger.py | Structured logging |

---

## How To Extend

### Add a New CMS

1. **Create Adapter** (`app/adapters/new_cms.py`):
```python
class NewCMSAdapter:
    async def fetch_content(self, url, site_url) -> NormalizedContent:
        # Fetch from API
        # Normalize to NormalizedContent
        return content
```

2. **Add Detection** (`app/layers/cms_detection.py`):
```python
async def _detect_new_cms(self, site_url, page_url) -> CMSDetectionResult:
    # Check for CMS-specific signals
    # Return result with cms_type=CMSType.NEW_CMS
```

3. **Add Routing** (`app/layers/ingestion.py`):
```python
if cms_result.cms_type == CMSType.NEW_CMS:
    return await self.new_cms_adapter.fetch_content(url)
```

4. **Update UI** (`app/static/index.html`):
```html
<option value="new_cms">New CMS</option>
```

### Add a New Schema Type

1. **Create Model** (`app/models/schema.py`):
```python
class EventSchema(SchemaBase):
    type: str = Field(default="Event", alias="@type")
    name: str
    startDate: Optional[str] = None
    location: Optional[str] = None
```

2. **Add Generation Logic** (`app/generators/schema_generator.py`):
```python
if content.content_type == ContentType.EVENT:
    return self._generate_event(content)

def _generate_event(self, content):
    schema = EventSchema(name=content.title, ...)
    return schema.to_jsonld()
```

3. **Add Content Type Detection** (`app/adapters/html_scraper.py`):
```python
if "/event" in url_lower:
    return ContentType.EVENT
```

---

## Common Debugging

**Q: Why is HTML scraping used instead of WordPress REST?**
Check logs for:
```json
{"event": "fallback_triggered", "from_source": "wordpress_rest", "reason": "..."}
```

**Q: Why does confidence score seem low?**
Check which fields are missing:
```json
{"event": "content_normalized", "fields_missing": ["description", "author"]}
```

**Q: How do I trace a specific request?**
Use the `trace_id` from the response to grep logs:
```bash
grep "a1b2c3d4" server.log
```

---

## Quick Reference Commands

```bash
# Start server
source sd_gen/bin/activate
uvicorn app.main:app --reload --port 8000

# Test health
curl http://localhost:8000/api/health

# Test CMS detection
curl "http://localhost:8000/api/detect-cms?url=https://wordpress.org"

# Test schema generation
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "mode": "html"}'
```
