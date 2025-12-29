"""
Normalized Content Model for the Structured Data Automation Tool.
This model represents the standardized format for all ingested content,
regardless of source (WordPress REST, Shopify API, or HTML scraping).
"""
from typing import List, Optional
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


class SourceType(str, Enum):
    """Source type indicating how content was obtained."""
    WORDPRESS_REST = "wordpress_rest"
    WORDPRESS_REST_AUTH = "wordpress_rest_authenticated"
    SHOPIFY_API = "shopify_api"
    HTML_SCRAPER = "html_scraper"


class ContentType(str, Enum):
    """Detected content type for schema generation."""
    ARTICLE = "article"
    BLOG_POST = "blog_post"
    SERVICE = "service"
    PRODUCT = "product"
    FAQ = "faq"
    ABOUT = "about"
    CONTACT = "contact"
    HOME = "home"
    UNKNOWN = "unknown"


class ImageData(BaseModel):
    """Image data extracted from content."""
    src: str
    alt: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class HeadingData(BaseModel):
    """Heading data with level and text."""
    level: int = Field(ge=1, le=6)
    text: str


class FAQItem(BaseModel):
    """FAQ question and answer pair."""
    question: str
    answer: str


class BreadcrumbItem(BaseModel):
    """Breadcrumb navigation item."""
    name: str
    url: Optional[str] = None
    position: int


class ProductVariant(BaseModel):
    """Product variant option."""
    name: str
    value: str
    price: Optional[str] = None
    sku: Optional[str] = None
    available: bool = True


class ProductOffer(BaseModel):
    """Product offer with price and availability."""
    price: str
    currency: str = "USD"
    availability: str = "InStock"  # InStock, OutOfStock, PreOrder
    price_valid_until: Optional[str] = None
    seller_name: Optional[str] = None


class AggregateRatingData(BaseModel):
    """Aggregate rating data."""
    rating_value: float = Field(ge=0.0, le=5.0)
    review_count: int = Field(ge=0)
    best_rating: float = 5.0
    worst_rating: float = 1.0


class ProductCapabilities(BaseModel):
    """
    Capability flags describing what product data is AVAILABLE.
    
    These flags are inferred from extracted data only.
    They describe what IS present, not what SHOULD be present.
    
    Usage:
    - Logging: Track extraction success
    - Validation: Know what fields can be used
    - Debugging: Identify extraction gaps
    """
    has_price: bool = False
    has_currency: bool = False
    has_availability: bool = False
    has_rating: bool = False
    has_reviews: bool = False
    has_variants: bool = False
    has_delivery_info: bool = False
    has_sku: bool = False
    has_brand: bool = False
    has_mpn: bool = False
    has_product_images: bool = False
    
    def to_dict(self) -> dict:
        """Return capabilities as a dictionary for logging."""
        return {
            "has_price": self.has_price,
            "has_currency": self.has_currency,
            "has_availability": self.has_availability,
            "has_rating": self.has_rating,
            "has_reviews": self.has_reviews,
            "has_variants": self.has_variants,
            "has_delivery_info": self.has_delivery_info,
            "has_sku": self.has_sku,
            "has_brand": self.has_brand,
            "has_mpn": self.has_mpn,
            "has_product_images": self.has_product_images,
        }
    
    def get_available_capabilities(self) -> List[str]:
        """Return list of capabilities that are True."""
        return [k for k, v in self.to_dict().items() if v]
    
    def get_missing_capabilities(self) -> List[str]:
        """Return list of capabilities that are False."""
        return [k for k, v in self.to_dict().items() if not v]


class NormalizedContent(BaseModel):
    """
    Normalized content model - the single internal representation
    for all ingested content regardless of source.
    
    This is the contract between the Ingestion Layer and Schema Generator.
    """
    # Required fields
    url: str
    title: str
    
    # Content fields
    description: Optional[str] = None
    body: Optional[str] = None
    
    # Structured content
    headings: List[HeadingData] = Field(default_factory=list)
    images: List[ImageData] = Field(default_factory=list)
    faq: List[FAQItem] = Field(default_factory=list)
    breadcrumbs: List[BreadcrumbItem] = Field(default_factory=list)
    
    # Metadata
    content_type: ContentType = ContentType.UNKNOWN
    source_type: SourceType
    
    # Quality indicators
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.5)
    
    # Additional metadata (for schema generation)
    author: Optional[str] = None
    published_date: Optional[str] = None
    modified_date: Optional[str] = None
    
    # Organization/Business info (if detected)
    organization_name: Optional[str] = None
    organization_logo: Optional[str] = None
    
    # Product-specific fields (from script JSON extraction)
    product_sku: Optional[str] = None
    product_mpn: Optional[str] = None  # Manufacturer Part Number
    product_brand: Optional[str] = None
    product_offer: Optional[ProductOffer] = None
    product_rating: Optional[AggregateRatingData] = None
    product_variants: List[ProductVariant] = Field(default_factory=list)
    product_images: List[str] = Field(default_factory=list)  # JSON-LD images (higher priority)
    
    # Delivery/shipping info (plain text)
    delivery_info: Optional[str] = None
    
    # Capability flags (computed from extracted data)
    capabilities: Optional[ProductCapabilities] = None
    
    def compute_capabilities(self) -> ProductCapabilities:
        """
        Compute capability flags based on extracted data.
        
        This method infers capabilities from what data IS present,
        not from what data SHOULD be present.
        """
        caps = ProductCapabilities(
            has_price=bool(self.product_offer and self.product_offer.price and self.product_offer.price != "0.00"),
            has_currency=bool(self.product_offer and self.product_offer.currency),
            has_availability=bool(self.product_offer and self.product_offer.availability),
            has_rating=bool(self.product_rating and self.product_rating.rating_value is not None),
            has_reviews=bool(self.product_rating and self.product_rating.review_count and self.product_rating.review_count > 0),
            has_variants=bool(self.product_variants and len(self.product_variants) > 0),
            has_delivery_info=bool(self.delivery_info),
            has_sku=bool(self.product_sku),
            has_brand=bool(self.product_brand),
            has_mpn=bool(self.product_mpn),
            has_product_images=bool(self.product_images and len(self.product_images) > 0),
        )
        self.capabilities = caps
        return caps
    
    def get_present_fields(self) -> List[str]:
        """Return list of non-empty fields."""
        present = ["url", "title", "source_type"]
        if self.description:
            present.append("description")
        if self.body:
            present.append("body")
        if self.headings:
            present.append("headings")
        if self.images:
            present.append("images")
        if self.faq:
            present.append("faq")
        if self.breadcrumbs:
            present.append("breadcrumbs")
        if self.author:
            present.append("author")
        if self.published_date:
            present.append("published_date")
        if self.product_offer:
            present.append("product_offer")
        if self.product_rating:
            present.append("product_rating")
        if self.product_variants:
            present.append("product_variants")
        if self.product_sku:
            present.append("product_sku")
        if self.product_brand:
            present.append("product_brand")
        if self.delivery_info:
            present.append("delivery_info")
        return present
    
    def get_missing_fields(self) -> List[str]:
        """Return list of empty optional fields."""
        all_optional = [
            "description", "body", "headings", "images", 
            "faq", "breadcrumbs", "author", "published_date",
            "product_offer", "product_rating", "product_sku",
            "product_brand", "delivery_info"
        ]
        present = self.get_present_fields()
        return [f for f in all_optional if f not in present]
