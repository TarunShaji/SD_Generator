# 🔧 Structured Data Automation Tool

A production-ready SEO tool that automatically generates **schema.org JSON-LD** structured data for individual web pages. Built with a REST-first architecture, HTML fallback capabilities, and a modern dual-mode UI.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-teal)

---

## 📋 Table of Contents

- [Overview](#overview)
- [v1 CMS Support Matrix](#v1-cms-support-matrix)
- [Key Features](#key-features)
- [Decision Flow](#decision-flow)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Supported Schema Types](#supported-schema-types)
- [What This Tool Does NOT Do](#what-this-tool-does-not-do)
- [Project Structure](#project-structure)
- [Logging System](#logging-system)
- [Development](#development)
- [Disclaimers](#disclaimers)

---

## Overview

The Structured Data Automation Tool generates schema.org-compliant JSON-LD structured data from any webpage. It follows a **REST-first** approach, preferring CMS REST APIs for data extraction while using HTML scraping as a fallback or explicit user-selected mode.

### Core Principles

| Principle | Description |
|-----------|-------------|
| **REST API First** | Always attempt to use CMS REST APIs before scraping |
| **HTML Scraping Second** | Used only as fallback or explicit user choice |
| **OAuth Optional & Isolated** | Never auto-triggered; fully user-controlled |
| **No Direct Database Access** | Only interfaces with public APIs |
| **CMS-Agnostic Ingestion** | Unified content model regardless of source |
| **Deterministic Logic** | No inferred or fabricated values; only output what data supports |
| **Detailed Logging** | Every decision is logged with trace IDs |

---

## v1 CMS Support Matrix

This section explicitly defines what is supported in v1:

| CMS Platform | Detection | Data Ingestion | Authentication | Notes |
|-------------|-----------|----------------|----------------|-------|
| **WordPress (self-hosted)** | ✅ Supported | REST API | None required | Public `/wp-json/` endpoint used |
| **WordPress.com** | ✅ Supported | REST API | OAuth (optional, user-triggered) | OAuth offered only if REST blocked |
| **Shopify** | ✅ Detected | HTML scraping only | N/A | API architecture ready, not implemented in v1 |
| **Unknown CMS** | Best-effort | HTML scraping only | N/A | Fallback is intentional behavior |

### CMS Detection Is Best-Effort

> **Important**: CMS detection relies on publicly exposed signals (HTTP endpoints, response headers, page content patterns). Detection is **not guaranteed** to be accurate for all sites. When detection is ambiguous or fails, the system intentionally falls back to HTML scraping. This is correct behavior, not a bug.

### Authentication Classification

When a 401/403 response is received, the system **classifies** the authentication requirement rather than assuming OAuth:

| Scenario | `auth_required` | Behavior |
|----------|-----------------|----------|
| WordPress.com domain | `OAUTH` | Offer "Connect WordPress.com" button |
| Self-hosted WordPress | `UNKNOWN` | Fall back to HTML (no OAuth prompt) |
| No auth needed (200) | `NONE` | Use REST directly |

> **Design Principle**: Authentication is a capability, not an assumption. OAuth is only offered when explicitly classified as the correct method.

---

## Key Features

### 🏢 CMS-Based Mode (Recommended)
- **WordPress Integration**: Full REST API support for self-hosted WordPress sites
- **WordPress.com OAuth**: Optional, user-triggered authentication for WordPress.com hosted sites
- **Shopify Detection**: Identifies Shopify stores, uses HTML scraping (API ready for future)
- **Automatic Detection**: Best-effort CMS identification with graceful fallback

### 📄 HTML-Only Mode
- Works with any website
- No credentials required
- Extracts title, meta, headings, body, images, FAQs, breadcrumbs
- **Script JSON Extraction**: Parses embedded JSON from `<script>` tags
- Content type detection (Article, Blog, Service, Product, FAQ, etc.)

### 💰 E-Commerce Product Support
- **Price & Currency**: Extracted from JSON-LD (preferred) or inline JS
- **Availability**: InStock, OutOfStock, PreOrder, LimitedAvailability
- **Aggregate Ratings**: Rating value and review count
- **Product Variants**: Name, price, SKU for each variant
- **MPN (Manufacturer Part Number)**: Extracted from JSON-LD
- **Product Images**: Preserves JSON-LD image arrays
- **Trust-Based Merge**: JSON-LD data takes priority over DOM/JS sources
- Generates full `Product` schema with `Offer` and `AggregateRating`

### 🎨 Premium UI
- Dark theme with animated gradient backgrounds
- Glassmorphism effects with backdrop blur
- Floating orb animations
- Shine effects on hover
- JetBrains Mono for code display
- Responsive design

---

## Decision Flow

The following text-based flow describes how the system routes requests:

```
URL Submitted
     │
     ▼
┌─────────────────────────────┐
│   Mode Selected by User?    │
└─────────────────────────────┘
     │                    │
     ▼                    ▼
[CMS-Based Mode]    [HTML-Only Mode]
     │                    │
     ▼                    │
┌─────────────────┐       │
│  CMS Detection  │       │
│  (Best-Effort)  │       │
└─────────────────┘       │
     │                    │
     ├── WordPress + REST 200 ────────────► REST Ingestion (no auth)
     │
     ├── WordPress + REST 401/403
     │        │
     │        ├── WordPress.com (auth_required=OAUTH)
     │        │        │
     │        │        ├── User approves ──────────► REST Ingestion (with auth)
     │        │        │
     │        │        └── User declines ──────────► HTML Fallback
     │        │
     │        └── Self-hosted (auth_required=UNKNOWN) ──► HTML Fallback
     │
     ├── Shopify Detected ────────────────► HTML Fallback (API not in v1)
     │
     └── Unknown CMS ─────────────────────► HTML Fallback
                                                   │
                                                   │
─────────────────────────────────────────────────────
                                                   │
                                                   ▼
                                    ┌──────────────────────┐
                                    │  Normalized Content  │
                                    │       Model          │
                                    └──────────────────────┘
                                                   │
                                                   ▼
                                    ┌──────────────────────┐
                                    │   Schema Generator   │
                                    │   (Deterministic)    │
                                    └──────────────────────┘
                                                   │
                                                   ▼
                                          JSON-LD Output
```

---

## Architecture

The system follows a **three-layer architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                      FRONTEND UI                             │
│         Mode Selection → Form Input → Results Display        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND                           │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────┐ ┌──────────────┐ ┌──────────────────┐   │
│  │  Layer 1:     │ │  Layer 2:    │ │    Layer 3:      │   │
│  │ CMS Detection │→│ Auth Layer   │→│  Ingestion Layer │   │
│  │  (Gatekeeper) │ │  (Optional)  │ │ (Source-Agnostic)│   │
│  └───────────────┘ └──────────────┘ └──────────────────┘   │
│                                              │               │
│                              ┌───────────────┼───────────────┐
│                              ▼               ▼               ▼
│                    ┌──────────────┐ ┌───────────┐ ┌─────────┐
│                    │  WordPress   │ │  Shopify  │ │  HTML   │
│                    │   Adapter    │ │ (stubbed) │ │ Scraper │
│                    └──────────────┘ └───────────┘ └─────────┘
│                                              │               │
│                              ┌───────────────┴───────────────┘
│                              ▼
│                    ┌──────────────────────┐
│                    │  Normalized Content  │
│                    └──────────────────────┘
│                              │
│                              ▼
│                    ┌──────────────────────┐
│                    │   Schema Generator   │
│                    │   (Deterministic)    │
│                    └──────────────────────┘
└─────────────────────────────────────────────────────────────┘
```

### Layer 1: CMS Detection Layer (Gatekeeper)

**Purpose**: Determine CMS type and REST API availability (best-effort).

**WordPress Detection**:
1. Probe `GET /wp-json/`
2. Evaluate response:
   - `200 OK` → WordPress (self-hosted), REST available
   - `401/403` → WordPress detected, REST blocked (possible WordPress.com)
   - `404` → Not WordPress

**Shopify Detection**:
- Check for Shopify-specific headers
- Detect CDN patterns (cdn.shopify.com)

### Layer 2: Authentication Layer (Optional)

**Purpose**: Provide authenticated REST access for WordPress.com sites only.

**OAuth Rules (Locked)**:
- ❌ OAuth is **never** auto-triggered
- ✅ OAuth is **user-initiated only** (explicit button click)
- ✅ OAuth exists **solely** to support WordPress.com–hosted sites
- ✅ OAuth is completely isolated from the default flow

Only activated when **all conditions** are met:
1. WordPress.com is detected
2. REST returns 401/403
3. User explicitly clicks "Connect CMS"

### Layer 3: Ingestion Layer

**Purpose**: Source-agnostic content consumption

- Normalizes all inputs into a unified content model
- CMS type, auth method, and OAuth tokens are invisible here
- Handles automatic fallback logic

---

## Installation

### Prerequisites
- Python 3.10+
- pip

### Quick Start

```bash
# Navigate to project directory
cd /path/to/Structured_data_generator

# Activate virtual environment
source sd_gen/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 8000
```

### Access the Application
- **Web UI**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/health

---

## Usage

### Using the Web UI

1. **Select Mode** (Required first step):
   - **CMS-Based** (Recommended): For WordPress sites with API access
   - **HTML-Only**: For any website, no credentials needed

2. **Select CMS** (CMS-Based mode only):
   - Auto-detect, WordPress, or Shopify

3. **Enter URL**: Paste the page URL you want to generate schema for

4. **Generate**: Click "Generate Schema" and wait for results

5. **Copy Output**: Use the copy buttons to grab the JSON-LD or script tag

### Credential Requirements (Displayed in UI)

| Mode | Credential Requirements |
|------|------------------------|
| CMS-Based (WordPress self-hosted) | None required |
| CMS-Based (WordPress.com) | OAuth optional, user-triggered |
| CMS-Based (Shopify) | None (HTML fallback in v1) |
| HTML-Only | None required |

### Using the API

#### Detect CMS Type
```bash
curl "http://localhost:8000/api/detect-cms?url=https://example.com"
```

#### Generate Schema (HTML Mode)
```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "mode": "html"}'
```

#### Generate Schema (CMS Mode)
```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wordpress.org/news/", "mode": "cms"}'
```

---

## API Reference

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/detect-cms` | Detect CMS type for URL |
| `POST` | `/api/generate` | Generate structured data |
| `GET` | `/api/oauth/wordpress/initiate` | Start WordPress OAuth (optional, user-triggered) |
| `GET` | `/api/oauth/wordpress/callback` | OAuth callback handler |

### Generate Request Schema

```json
{
  "url": "string",          // Required: Page URL to analyze
  "mode": "cms | html",     // Required: Generation mode
  "cms_type": "string"      // Optional: Force CMS type (wordpress, shopify)
}
```

### Generate Response Schema

```json
{
  "url": "string",
  "mode": "string",
  "cms_detected": "string | null",
  "source_used": "string",
  "content_type": "string",
  "confidence": 0.0-1.0,
  "schemas": [...],
  "script_tag": "string",
  "trace_id": "string"
}
```

### Understanding the `confidence` Score

The `confidence` score (0.0–1.0) reflects **extraction completeness**, not SERP eligibility:

| Score | Meaning |
|-------|---------|
| 0.8–1.0 | High-quality extraction: title, description, body, and structure present |
| 0.5–0.7 | Moderate extraction: some fields missing or incomplete |
| 0.0–0.4 | Low extraction: limited data available from source |

---

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json  # or "console"

# WordPress OAuth (Optional - for WordPress.com sites ONLY)
# OAuth is NEVER auto-triggered. User must explicitly initiate.
# ALL THREE variables must be set for OAuth to be available.
WP_OAUTH_CLIENT_ID=your_client_id
WP_OAUTH_CLIENT_SECRET=your_client_secret
WP_OAUTH_REDIRECT_URI=http://localhost:8000/api/oauth/wordpress/callback

# Shopify API (Reserved for future use - not implemented in v1)
SHOPIFY_API_KEY=
SHOPIFY_API_SECRET=

# Request Settings
REQUEST_TIMEOUT=30
```

### OAuth Configuration Requirements

| Variable | Required | Description |
|----------|----------|-------------|
| `WP_OAUTH_CLIENT_ID` | Yes (for OAuth) | WordPress.com Developer App Client ID |
| `WP_OAUTH_CLIENT_SECRET` | Yes (for OAuth) | WordPress.com Developer App Client Secret |
| `WP_OAUTH_REDIRECT_URI` | Yes (for OAuth) | Must match WordPress.com app settings |

> **If any OAuth variable is missing**, OAuth is gracefully disabled with clear logging. The tool continues to work with HTML fallback.

---

## Supported Schema Types

### Schema Generation Philosophy (v1)

> **Deterministic v1**: Schema generation in v1 is rule-based and deterministic. All output values are directly derived from extracted content—no inference, no fabrication, no hallucination. Future iterations may refine the mapping logic, but this is planned evolution, not a limitation.

| Content Type | Schema Generated |
|-------------|------------------|
| Blog Post | `BlogPosting` |
| Article | `Article` |
| Service Page | `Service` |
| Product Page | `Product` |
| FAQ Content | `FAQPage` (if ≥2 Q&As detected) |
| Navigation | `BreadcrumbList` (if present in content) |
| Organization Info | `Organization` (if detected) |
| General Page | `WebPage` |

### Example Output

```json
{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "Getting Started with WordPress",
  "description": "A comprehensive guide to WordPress...",
  "image": "https://example.com/image.jpg",
  "author": {
    "@type": "Person",
    "name": "John Doe"
  },
  "datePublished": "2024-01-15T10:00:00Z",
  "mainEntityOfPage": "https://example.com/blog/getting-started"
}
```

---

## What This Tool Does NOT Do

This section documents intentional **non-goals** for v1:

| Non-Goal | Explanation |
|----------|-------------|
| ❌ **No CMS writes** | Tool is read-only; does not modify source sites |
| ❌ **No automatic schema injection** | User must manually add output to their site |
| ❌ **No crawling** | Processes single URLs only; no spidering |
| ❌ **No guaranteed rich results** | See [Rich Results Disclaimer](#rich-results-disclaimer) |
| ❌ **No inference of missing facts** | Will not fabricate author, date, or other missing data |
| ❌ **No OAuth auto-initiation** | OAuth is strictly user-triggered |
| ❌ **No Shopify API in v1** | API architecture exists but is not active |

---

## Disclaimers

### Rich Results Disclaimer

> **Important**: Generating schema.org-compliant JSON-LD does **not** guarantee Google rich results in SERPs.
>
> - Google controls rich result eligibility independently
> - Meeting schema.org syntax ≠ meeting Google's quality thresholds
> - Rich result display depends on many factors outside this tool's control
> - The `confidence` score reflects extraction completeness, **not** SERP eligibility
>
> Use [Google's Rich Results Test](https://search.google.com/test/rich-results) to validate generated schemas.

### Detection Disclaimer

CMS detection is best-effort based on publicly available signals. The tool may misidentify or fail to identify certain CMS platforms. HTML fallback is the intentional and correct behavior for ambiguous cases.

---

## Project Structure

```
Structured_data_generator/
├── sd_gen/                    # Virtual environment
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI application entry point
│   ├── config.py             # Configuration management
│   ├── models/
│   │   ├── __init__.py
│   │   ├── content.py        # Normalized content model
│   │   └── schema.py         # JSON-LD schema models
│   ├── layers/
│   │   ├── __init__.py
│   │   ├── cms_detection.py  # Layer 1: CMS Detection
│   │   ├── auth.py           # Layer 2: Authentication (optional)
│   │   └── ingestion.py      # Layer 3: Ingestion
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── wordpress.py      # WordPress REST adapter
│   │   ├── shopify.py        # Shopify API adapter (stubbed for v1)
│   │   └── html_scraper.py   # HTML scraping fallback
│   ├── generators/
│   │   ├── __init__.py
│   │   └── schema_generator.py # JSON-LD generation (deterministic)
│   ├── utils/
│   │   ├── __init__.py
│   │   └── logger.py         # Structured logging
│   └── static/
│       ├── index.html        # Frontend UI
│       ├── style.css         # Dark theme styling
│       └── app.js            # Frontend logic
├── requirements.txt
└── README.md
```

---

## Logging System

The tool uses **structlog** for structured, JSON-formatted logging with trace IDs.

### Log Features
- **Trace ID**: Every request gets a unique trace ID for debugging
- **Layer Names**: Each log entry includes which layer generated it
- **Decision Logging**: All routing decisions are logged with reasons
- **Fallback Logging**: Clearly documents why fallbacks occurred

### Example Log Output

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "level": "info",
  "trace_id": "a1b2c3d4",
  "layer": "cms_detection",
  "event": "decision_made",
  "decision": "wordpress_detected",
  "reason": "REST API returned valid WordPress response",
  "url": "https://example.com",
  "rest_available": true,
  "next_step": "use_rest_api"
}
```

---

## Development

### Adding a New CMS

1. Create adapter in `app/adapters/new_cms.py`
2. Add detection logic in `app/layers/cms_detection.py`
3. Add routing in `app/layers/ingestion.py`
4. Update UI in `app/static/index.html`

### Adding New Schema Types

1. Add Pydantic model in `app/models/schema.py`
2. Add generation logic in `app/generators/schema_generator.py`
3. Update content type detection in adapters

### Running Tests

```bash
# Activate virtual environment
source sd_gen/bin/activate

# Health check
curl http://localhost:8000/api/health

# CMS Detection
curl "http://localhost:8000/api/detect-cms?url=https://wordpress.org"

# Schema Generation
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "mode": "html"}'
```

---

## Roadmap

Future iterations may include:

- [ ] Full Shopify Storefront API integration
- [ ] Support for additional CMS platforms (Drupal, Joomla)
- [ ] Batch URL processing
- [ ] Schema validation against Google Rich Results
- [ ] Export to multiple formats (RDFa, Microdata)

---

## License

This project is for internal use. All rights reserved.

---

## Credits

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) - HTML parsing
- [httpx](https://www.python-httpx.org/) - Async HTTP client
- [structlog](https://www.structlog.org/) - Structured logging
- [Pydantic](https://docs.pydantic.dev/) - Data validation
