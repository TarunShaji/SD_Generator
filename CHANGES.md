# Changelog

All notable changes to the Structured Data Automation Tool are documented in this file.

## [Unreleased] - 2025-12-29

### JSON-LD Completeness Fixes

This release addresses several systemic extraction gaps in the HTML scraper, improving JSON-LD parsing completeness without overfitting to any specific site or CMS.

---

### 🔧 Fix 1: Full @graph Iteration

**Problem:** The JSON-LD parser only extracted `Product` nodes from `@graph`, ignoring other schema types like `BreadcrumbList`, `Organization`, etc.

**Solution:** 
- Updated `_extract_breadcrumbs()` to iterate through `@graph` arrays
- Now handles: direct `BreadcrumbList`, `BreadcrumbList` inside `@graph`, and arrays of schemas
- Priority: JSON-LD breadcrumbs > DOM breadcrumbs

**Files Changed:**
- `app/adapters/html_scraper.py` → `_extract_breadcrumbs()`, `_parse_breadcrumb_list()`

---

### 🔧 Fix 2: Trust-Based Merge Precedence

**Problem:** The previous merge logic used "first non-None wins", which meant lower-trust DOM data could override authoritative JSON-LD data.

**Solution:** Implemented `_trust_based_merge()` with explicit field-level precedence:

| Field | Priority Order |
|-------|----------------|
| `price/offers` | JSON-LD > JS State > DOM |
| `availability` | JSON-LD > JS State > DOM |
| `images` | JSON-LD > DOM |
| `rating` | JSON-LD > JS State > DOM |
| `variants` | JS State > DOM |
| `sku/mpn/brand` | JSON-LD > JS State > DOM |
| `delivery_text` | DOM only |

**Files Changed:**
- `app/adapters/html_scraper.py` → `_trust_based_merge()`, `_extract_script_json_data()`

---

### 🔧 Fix 3: JSON-LD Image Extraction

**Problem:** The parser ignored `image` fields in JSON-LD Product schemas entirely.

**Solution:**
- Added `_normalize_jsonld_images()` to extract images from JSON-LD
- Handles: string, `List[str]`, `List[ImageObject]`, single `ImageObject`
- Preserves full image array instead of collapsing to single image

**Files Changed:**
- `app/adapters/html_scraper.py` → `_parse_jsonld_product()`, `_normalize_jsonld_images()`
- `app/models/content.py` → Added `product_images: List[str]`

---

### 🔧 Fix 4: MPN (Manufacturer Part Number) Support

**Problem:** `mpn` was completely ignored during parsing, despite being a valid Product schema field.

**Solution:** End-to-end MPN support:
- Parse `mpn` from JSON-LD Product
- Store in `NormalizedContent.product_mpn`
- Track via `capabilities.has_mpn`
- Output in `ProductSchema.mpn`

**Files Changed:**
- `app/models/content.py` → Added `product_mpn: Optional[str]`, `has_mpn` capability
- `app/models/schema.py` → Added `mpn: Optional[str]` to `ProductSchema`
- `app/adapters/html_scraper.py` → Extract `mpn` in `_parse_jsonld_product()`
- `app/generators/schema_generator.py` → Include `mpn` in Product schema output

---

### 🔧 Fix 5: BreadcrumbList from @graph

**Problem:** `_extract_breadcrumbs()` only checked for direct `BreadcrumbList` type, missing breadcrumbs inside `@graph` containers.

**Solution:** Covered by Fix 1 - `_extract_breadcrumbs()` now handles all JSON-LD formats.

---

### 📊 New Capability Flags

Added to `ProductCapabilities`:
- `has_mpn: bool` - MPN available
- `has_product_images: bool` - JSON-LD images available

---

### 📝 Logging Enhancements

New structured log events:

```json
{"event": "trust_based_merge", "decisions": [{"field": "product_offer", "source": "jsonld"}, ...]}
{"event": "breadcrumb_extraction", "status": "found_in_graph", "count": 3}
```

---

### ⚠️ What Was NOT Changed

- **Schema generator logic** - Still outputs only what is in `NormalizedContent`
- **Determinism** - Same input → same output guaranteed
- **Source isolation** - Scraper extracts, generator formats
- **No site-specific logic** - All fixes are generic

---

### 🧪 Testing

Test with any product page containing JSON-LD structured data:
1. Verify `product_offer` comes from JSON-LD (check `trust_based_merge` log)
2. Verify breadcrumbs are extracted from `@graph` if present
3. Verify `mpn` appears in output if present in JSON-LD
4. Verify images use JSON-LD source when available

---

## Changes New: Unified JSON-LD Architecture (2025-12-29)

### 🏗️ Architectural Refactor: Single-Pass JSON-LD Parsing

**Problem:** JSON-LD was parsed in multiple isolated functions with inconsistent traversal:
- Product extraction parsed `@graph` separately
- Breadcrumb extraction did a separate parse
- No shared state between parsers
- Risk of duplicate parsing and missed nodes

**Solution:** Implemented unified JSON-LD graph walker with single-pass parsing.

---

### New Functions

| Function | Purpose |
|----------|---------|
| `_parse_all_jsonld()` | Parse ALL JSON-LD scripts ONCE, organize by `@type` |
| `_flatten_jsonld()` | Flatten `@graph`, arrays, nested structures |
| `_extract_from_jsonld_layer_unified()` | Extract Product from pre-parsed graph |
| `_extract_breadcrumbs_unified()` | Extract BreadcrumbList from pre-parsed graph |

---

### New Flow

```
_parse_html()
    │
    ├─► _parse_all_jsonld(soup)           # SINGLE PASS
    │       └─► _flatten_jsonld()          # Handles @graph, arrays
    │           Returns: {"Product": [...], "BreadcrumbList": [...], ...}
    │
    ├─► _extract_script_json_data(soup, jsonld_graph)
    │       └─► _extract_from_jsonld_layer_unified()  # Uses pre-parsed
    │
    └─► _extract_breadcrumbs_unified(soup, url, jsonld_graph)
            # Uses pre-parsed BreadcrumbList nodes
```

---

### New Logging

```json
{"event": "jsonld_unified_parse", "types_found": {"Product": 1, "BreadcrumbList": 1}, "total_nodes": 2}
{"event": "jsonld_extraction_unified", "fields_found": ["sku", "product_offer"], "product_nodes_found": 1}
{"event": "breadcrumb_extraction", "status": "from_jsonld_unified", "count": 4}
```

---

### Benefits

1. **No duplicate parsing** - JSON-LD parsed exactly once
2. **@graph fully traversed** - All node types extracted
3. **BreadcrumbList never missed** - Uses pre-parsed graph
4. **Extensible** - Easy to add Organization, WebPage extraction later
5. **Deterministic** - Same input → same output

---

### Files Changed

- `app/adapters/html_scraper.py`:
  - Added `_parse_all_jsonld()`, `_flatten_jsonld()`
  - Added `_extract_from_jsonld_layer_unified()`
  - Added `_extract_breadcrumbs_unified()`
  - Updated `_parse_html()` to use unified parser
  - Updated `_extract_script_json_data()` to accept pre-parsed graph

---

## WordPress.com REST API Fix (2025-12-29)

### 🏗️ Problem

WordPress.com sites (e.g., `site.wordpress.com`) return 404 for `/wp-json/`, causing:
- CMS classified as `UNKNOWN`
- Falls back to HTML scraping
- OAuth never invoked
- WordPress.com REST API never reached

### ✅ Solution

Implemented early WordPress.com detection and proper public API routing.

---

### 1. Early Domain Detection (`cms_detection.py`)

**Before** probing `/wp-json/`, check if domain ends with `.wordpress.com`:

```python
if domain.endswith(".wordpress.com"):
    # Skip /wp-json probe - use public API instead
```

---

### 2. WordPress.com Public API Probe

Probe the correct API:
```
https://public-api.wordpress.com/rest/v1.1/sites/{domain}
```

---

### 3. WordPress.com Adapter Methods (`wordpress.py`)

| Method | Purpose |
|--------|---------|
| `fetch_content_wordpress_com()` | Fetch content from WordPress.com public API |
| `_find_content_wordpress_com()` | Find pages/posts via `/posts?type=page&slug={slug}` |
| `_normalize_wordpress_com_content()` | Normalize WordPress.com API response |

---

### 4. Ingestion Routing (`ingestion.py`)

WordPress.com now routes to `fetch_content_wordpress_com()`:
```python
if cms_result.cms_type == CMSType.WORDPRESS_COM:
    return await adapter.fetch_content_wordpress_com(url, site_domain)
```

---

### Extensive Logging

```json
{"event": "wordpress_com_early_detection", "domain_match": true, "domain": "site.wordpress.com"}
{"event": "wordpress_com_public_api_probe", "status": "success", "site_name": "My Site"}
{"event": "wordpress_com_api_request", "status": "trying_pages", "slug": "about"}
{"event": "wordpress_com_content_found", "type": "page", "title": "About Us"}
```

---

### Files Changed

| File | Changes |
|------|---------|
| `app/layers/cms_detection.py` | Early `.wordpress.com` detection, `_detect_wordpress_com_public_api()` |
| `app/adapters/wordpress.py` | `fetch_content_wordpress_com()`, `_find_content_wordpress_com()`, `_normalize_wordpress_com_content()` |
| `app/layers/ingestion.py` | Route `CMSType.WORDPRESS_COM` to public API |

---

## Previous Changes

See git history for earlier changes.

