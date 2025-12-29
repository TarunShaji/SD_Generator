# HTML Scraping Flow - Technical Breakdown

This document provides an in-depth technical breakdown of how structured data (JSON-LD schemas) is generated from scraped HTML.

---

## High-Level Flow

```
URL Input
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                      HTML SCRAPER                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 1. HTTP Fetch                                           │    │
│  │    • GET request with timeout                           │    │
│  │    • Follow redirects                                   │    │
│  │    • Return raw HTML                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 2. Unified JSON-LD Parsing (SINGLE PASS)                │    │
│  │    • Parse ALL <script type="application/ld+json">      │    │
│  │    • Flatten @graph containers                          │    │
│  │    • Organize by @type: {Product: [...], ...}           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 3. Three-Layer Product Extraction                       │    │
│  │    • Layer 1: DOM (price, availability, variants)       │    │
│  │    • Layer 2: JSON-LD (offers, rating, images)          │    │
│  │    • Layer 3: JS State (window.product, etc.)           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 4. Trust-Based Merge                                    │    │
│  │    • JSON-LD wins for: price, offers, rating, images    │    │
│  │    • JS State wins for: variants                        │    │
│  │    • DOM only for: delivery text                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 5. Content Extraction                                   │    │
│  │    • Title, Description, Body text                      │    │
│  │    • Headings (H1-H6)                                   │    │
│  │    • Images, FAQs, Breadcrumbs                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 6. NormalizedContent Model                              │    │
│  │    • Unified data contract                              │    │
│  │    • compute_capabilities() → ProductCapabilities       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SCHEMA GENERATOR                              │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 7. Content Type Detection                               │    │
│  │    • Product, Article, Service, FAQ, etc.               │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 8. Schema Generation                                    │    │
│  │    • Generate appropriate schema.org type               │    │
│  │    • Include only fields with data                      │    │
│  │    • Respect capability flags                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                      │
│                           ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 9. Output                                               │    │
│  │    • JSON-LD script tag                                 │    │
│  │    • Ready for HTML injection                           │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
              JSON-LD Schema Output
```

---

## Detailed Technical Breakdown

### 1. HTTP Fetch

**File:** `app/adapters/html_scraper.py` → `fetch_and_parse()`

```python
async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
    response = await client.get(url, headers={
        "User-Agent": "...",
        "Accept": "text/html,application/xhtml+xml..."
    })
```

**Behavior:**
- Uses `httpx` async HTTP client
- 30-second timeout
- Follows redirects automatically
- Returns raw HTML string

---

### 2. Unified JSON-LD Parsing

**File:** `app/adapters/html_scraper.py` → `_parse_all_jsonld()`

This is the **SINGLE entry point** for all JSON-LD extraction. It parses every `<script type="application/ld+json">` tag exactly once.

```python
def _parse_all_jsonld(self, soup) -> Dict[str, List[Dict]]:
    """
    Returns: {"Product": [...], "BreadcrumbList": [...], ...}
    """
    for script in soup.find_all("script", type="application/ld+json"):
        data = json.loads(script.string)
        nodes = self._flatten_jsonld(data)
        # Organize by @type
```

**`_flatten_jsonld()` handles:**

| Structure | Example | Handling |
|-----------|---------|----------|
| Single object | `{"@type": "Product", ...}` | Return as single node |
| Array | `[{"@type": "Product"}, {"@type": "Organization"}]` | Return each as node |
| @graph | `{"@graph": [{...}, {...}]}` | Flatten and return each |
| Nested | `{"@type": "Product", "offers": {"@type": "Offer"}}` | Return parent node |

**Output:**
```json
{
  "Product": [{"@type": "Product", "name": "..."}],
  "BreadcrumbList": [{"@type": "BreadcrumbList", ...}],
  "Organization": [{"@type": "Organization", ...}]
}
```

---

### 3. Three-Layer Product Extraction

**File:** `app/adapters/html_scraper.py` → `_extract_script_json_data()`

Product data is extracted from **three independent sources**:

#### Layer 1: Visible DOM (Confidence: 0.6)

```python
def _extract_from_visible_dom(self, soup) -> Dict:
```

| Selector Pattern | Data Extracted |
|------------------|----------------|
| `[itemprop="price"]`, `.price` | Price amount |
| `[itemprop="availability"]`, `.stock-status` | In Stock / Out of Stock |
| `select[name*="option"] option` | Variants |
| `.shipping-info`, `.delivery-info` | Delivery text |

#### Layer 2: JSON-LD (Confidence: 0.9)

```python
def _extract_from_jsonld_layer_unified(self, jsonld_graph) -> Dict:
```

Uses pre-parsed graph from Step 2:
```python
product_nodes = jsonld_graph.get("Product", [])
for product_data in product_nodes:
    parsed = self._parse_jsonld_product(product_data)
```

**`_parse_jsonld_product()` extracts:**

| JSON-LD Field | Extracted As |
|---------------|--------------|
| `sku` | `product_sku` |
| `mpn` | `product_mpn` |
| `brand.name` or `brand` | `product_brand` |
| `offers` / `offers.price` | `product_offer` (ProductOffer object) |
| `aggregateRating` | `product_rating` (AggregateRatingData object) |
| `image` | `product_images` (List[str]) |

**Image normalization (`_normalize_jsonld_images()`):**

| Input Format | Output |
|--------------|--------|
| `"https://example.com/img.jpg"` | `["https://example.com/img.jpg"]` |
| `["img1.jpg", "img2.jpg"]` | `["img1.jpg", "img2.jpg"]` |
| `{"@type": "ImageObject", "url": "..."}` | `["..."]` |
| `[{"@type": "ImageObject", "url": "..."}]` | `["..."]` |

#### Layer 3: Embedded JS State (Confidence: 0.8)

```python
def _extract_from_js_state_layer(self, soup) -> Dict:
```

Searches for patterns like:
```javascript
window.product = {...}
window.__INITIAL_STATE__ = {...}
ShopifyAnalytics.meta.product = {...}
```

Uses regex to extract JSON blobs:
```python
patterns = [
    r'window\.product\s*=\s*(\{.*?\});',
    r'ShopifyAnalytics\.meta\.product\s*=\s*(\{.*?\});',
    ...
]
```

---

### 4. Trust-Based Merge

**File:** `app/adapters/html_scraper.py` → `_trust_based_merge()`

This is **NOT** first-value-wins. It's **field-specific priority**:

```python
def _trust_based_merge(self, dom_data, js_state_data, jsonld_data) -> Dict:
```

| Field | Priority Order | Rationale |
|-------|----------------|-----------|
| `sku` | JSON-LD > JS State > DOM | JSON-LD is authoritative |
| `brand` | JSON-LD > JS State > DOM | JSON-LD is authoritative |
| `product_offer` | JSON-LD > JS State > DOM | Price from structured data |
| `product_rating` | JSON-LD > JS State > DOM | Ratings from schema |
| `product_images` | JSON-LD > DOM | JSON-LD has curated images |
| `mpn` | JSON-LD > JS State | Only in structured data |
| `product_variants` | JS State > DOM | JS has variant details |
| `delivery_text` | DOM only | Not in structured data |

**Example:**
```python
# If JSON-LD has price=$29.99 and DOM has price=$19.99
# Result: price=$29.99 (JSON-LD wins)
```

---

### 5. Content Extraction

**File:** `app/adapters/html_scraper.py` → `_parse_html()`

#### Title Extraction
```python
def _extract_title(self, soup) -> str:
    # Priority: <title> tag > <h1> > "Untitled"
    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else "Untitled"
```

#### Meta Description
```python
def _extract_meta_description(self, soup) -> Optional[str]:
    meta = soup.find("meta", attrs={"name": "description"})
    return meta.get("content") if meta else None
```

#### Headings (H1-H6)
```python
def _extract_headings(self, soup) -> List[HeadingData]:
    headings = []
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            headings.append(HeadingData(level=level, text=h.get_text(strip=True)))
    return headings
```

#### Images
```python
def _extract_images(self, soup, base_url) -> List[ImageData]:
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        images.append(ImageData(
            src=urljoin(base_url, src),
            alt=img.get("alt"),
            width=img.get("width"),
            height=img.get("height")
        ))
    return images[:20]  # Limit to 20
```

#### FAQ Extraction
```python
def _extract_faq(self, soup) -> List[FAQItem]:
    # Pattern 1: JSON-LD FAQPage
    # Pattern 2: Accordion patterns
    # Pattern 3: Q&A heading patterns (H2/H3 ending with ?)
```

#### Breadcrumbs
```python
def _extract_breadcrumbs_unified(self, soup, url, jsonld_graph):
    # Priority: JSON-LD BreadcrumbList > DOM nav[aria-label="breadcrumb"]
    breadcrumb_nodes = jsonld_graph.get("BreadcrumbList", [])
```

---

### 6. NormalizedContent Model

**File:** `app/models/content.py`

All extracted data flows into a single **data contract**:

```python
class NormalizedContent(BaseModel):
    # Required
    url: str
    title: str
    source_type: SourceType
    
    # Content
    description: Optional[str]
    body: Optional[str]
    headings: List[HeadingData]
    images: List[ImageData]
    faq: List[FAQItem]
    breadcrumbs: List[BreadcrumbItem]
    
    # Product-specific
    product_offer: Optional[ProductOffer]
    product_rating: Optional[AggregateRatingData]
    product_variants: List[ProductVariant]
    product_sku: Optional[str]
    product_brand: Optional[str]
    product_mpn: Optional[str]
    product_images: List[str]
    
    # Metadata
    content_type: ContentType
    confidence_score: float
    author: Optional[str]
    published_date: Optional[str]
```

**Capability Computation:**

```python
def compute_capabilities(self) -> ProductCapabilities:
    return ProductCapabilities(
        has_price=self.product_offer is not None and self.product_offer.price is not None,
        has_currency=self.product_offer is not None and self.product_offer.currency is not None,
        has_availability=self.product_offer is not None and self.product_offer.availability is not None,
        has_rating=self.product_rating is not None,
        has_reviews=self.product_rating is not None and (self.product_rating.review_count or 0) > 0,
        has_variants=len(self.product_variants) > 0,
        has_sku=self.product_sku is not None,
        has_brand=self.product_brand is not None,
        has_mpn=self.product_mpn is not None,
        has_product_images=len(self.product_images) > 0,
    )
```

---

### 7. Content Type Detection

**File:** `app/adapters/html_scraper.py` → `_detect_content_type()`

```python
def _detect_content_type(self, soup, url, headings, faq) -> ContentType:
    # Check for product markers
    if soup.find(attrs={"itemtype": re.compile("Product")}):
        return ContentType.PRODUCT
    
    # Check for article markers
    if soup.find("article") or meta_type == "article":
        return ContentType.ARTICLE
    
    # URL-based detection
    if "/product" in url or "/shop" in url:
        return ContentType.PRODUCT
    if "/blog" in url or "/post" in url:
        return ContentType.BLOG_POST
    
    # FAQ detection
    if len(faq) > 2:
        return ContentType.FAQ
```

**Supported Content Types:**

| Type | Detection Signals |
|------|-------------------|
| `PRODUCT` | Product schema, /product URL, price elements |
| `ARTICLE` | `<article>` tag, og:type=article, /blog URL |
| `BLOG_POST` | /blog or /post in URL with article markers |
| `SERVICE` | /service URL, service-related headings |
| `FAQ` | FAQPage schema, 3+ Q&A pairs |
| `LOCAL_BUSINESS` | LocalBusiness schema |
| `UNKNOWN` | Default fallback |

---

### 8. Schema Generation

**File:** `app/generators/schema_generator.py`

The generator is **deterministic** - it only uses data from `NormalizedContent`.

```python
class SchemaGenerator:
    def generate(self, content: NormalizedContent) -> List[Dict]:
        schemas = []
        
        # Primary schema based on content type
        primary = self._generate_primary_schema(content)
        schemas.append(primary)
        
        # FAQ schema (if FAQs present)
        if content.faq:
            schemas.append(self._generate_faq_schema(content))
        
        # Breadcrumb schema (if breadcrumbs present)
        if content.breadcrumbs:
            schemas.append(self._generate_breadcrumb_schema(content))
        
        # Organization schema (from meta)
        if organization_name:
            schemas.append(self._generate_organization_schema())
        
        return schemas
```

#### Product Schema Generation

```python
def _generate_product(self, content: NormalizedContent) -> Dict:
    capabilities = content.compute_capabilities()
    
    schema = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": content.title,
        "description": content.description,
    }
    
    # Only include fields with data
    if capabilities.has_sku:
        schema["sku"] = content.product_sku
    
    if capabilities.has_mpn:
        schema["mpn"] = content.product_mpn
    
    if capabilities.has_brand:
        schema["brand"] = {"@type": "Brand", "name": content.product_brand}
    
    if capabilities.has_product_images:
        schema["image"] = content.product_images
    elif content.images:
        schema["image"] = content.images[0].src
    
    if capabilities.has_price:
        schema["offers"] = {
            "@type": "Offer",
            "price": content.product_offer.price,
            "priceCurrency": content.product_offer.currency,
            "availability": f"https://schema.org/{content.product_offer.availability}"
        }
    
    if capabilities.has_rating:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": content.product_rating.rating_value,
            "bestRating": content.product_rating.best_rating,
            "ratingCount": content.product_rating.rating_count
        }
        if capabilities.has_reviews:
            schema["aggregateRating"]["reviewCount"] = content.product_rating.review_count
    
    return schema
```

---

### 9. Output Format

**Final JSON-LD:**

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Example Product",
  "description": "Product description...",
  "sku": "12345",
  "brand": {"@type": "Brand", "name": "Example Brand"},
  "image": ["https://example.com/img1.jpg", "https://example.com/img2.jpg"],
  "offers": {
    "@type": "Offer",
    "price": "29.99",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.5",
    "bestRating": "5",
    "ratingCount": "120",
    "reviewCount": "45"
  }
}
</script>
```

---

## Key Design Principles

1. **Single-Pass JSON-LD Parsing** - Parse all scripts once, organize by type
2. **Trust-Based Merge** - JSON-LD > JS State > DOM for authoritative fields
3. **Capability-Driven Generation** - Only include fields with actual data
4. **Source Isolation** - Scraper extracts, generator formats
5. **Determinism** - Same input always produces same output
6. **No Site-Specific Logic** - Generic patterns only
