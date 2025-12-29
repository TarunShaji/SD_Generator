"""
Schema.org JSON-LD models for structured data generation.
These models ensure deterministic, Google-compatible output.
"""
from typing import List, Optional, Union, Dict, Any
from pydantic import BaseModel, Field


class SchemaBase(BaseModel):
    """Base class for all schema.org types."""
    
    def to_jsonld(self) -> Dict[str, Any]:
        """Convert to JSON-LD format, excluding None values."""
        data = {"@context": "https://schema.org"}
        for key, value in self.model_dump(exclude_none=True, by_alias=True).items():
            if key.startswith("_"):
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            data[key] = value
        return data


class BreadcrumbListItem(BaseModel):
    """Item within a BreadcrumbList."""
    type: str = Field(default="ListItem", alias="@type")
    position: int
    name: str
    item: Optional[str] = None  # URL


class BreadcrumbListSchema(SchemaBase):
    """BreadcrumbList schema for navigation."""
    type: str = Field(default="BreadcrumbList", alias="@type")
    itemListElement: List[BreadcrumbListItem] = Field(default_factory=list)


class FAQAnswer(BaseModel):
    """Answer within an FAQ."""
    type: str = Field(default="Answer", alias="@type")
    text: str


class FAQQuestion(BaseModel):
    """Question within an FAQ."""
    type: str = Field(default="Question", alias="@type")
    name: str
    acceptedAnswer: FAQAnswer


class FAQPageSchema(SchemaBase):
    """FAQPage schema for FAQ content."""
    type: str = Field(default="FAQPage", alias="@type")
    mainEntity: List[FAQQuestion] = Field(default_factory=list)


class ImageObjectSchema(BaseModel):
    """ImageObject for images within content."""
    type: str = Field(default="ImageObject", alias="@type")
    url: str
    caption: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class OrganizationSchema(SchemaBase):
    """Organization schema."""
    type: str = Field(default="Organization", alias="@type")
    name: str
    url: Optional[str] = None
    logo: Optional[str] = None
    description: Optional[str] = None


class LocalBusinessSchema(SchemaBase):
    """LocalBusiness schema - extends Organization."""
    type: str = Field(default="LocalBusiness", alias="@type")
    name: str
    url: Optional[str] = None
    logo: Optional[str] = None
    description: Optional[str] = None
    address: Optional[str] = None
    telephone: Optional[str] = None


class PersonSchema(BaseModel):
    """Person schema for authors."""
    type: str = Field(default="Person", alias="@type")
    name: str


class ArticleSchema(SchemaBase):
    """Article/BlogPosting schema."""
    type: str = Field(default="Article", alias="@type")
    headline: str
    description: Optional[str] = None
    image: Optional[Union[str, List[str]]] = None
    author: Optional[PersonSchema] = None
    publisher: Optional[Dict[str, Any]] = None  # Organization with logo
    datePublished: Optional[str] = None
    dateModified: Optional[str] = None
    mainEntityOfPage: Optional[str] = None


class BlogPostingSchema(ArticleSchema):
    """BlogPosting schema - specialized Article."""
    type: str = Field(default="BlogPosting", alias="@type")


class ServiceSchema(SchemaBase):
    """Service schema for service pages."""
    type: str = Field(default="Service", alias="@type")
    name: str
    description: Optional[str] = None
    provider: Optional[OrganizationSchema] = None
    serviceType: Optional[str] = None
    url: Optional[str] = None


class OfferSchema(BaseModel):
    """Offer schema for product pricing."""
    type: str = Field(default="Offer", alias="@type")
    price: str
    priceCurrency: str = "USD"
    availability: Optional[str] = None  # https://schema.org/InStock etc.
    priceValidUntil: Optional[str] = None
    seller: Optional[Dict[str, Any]] = None


class AggregateRatingSchema(BaseModel):
    """AggregateRating schema for product reviews."""
    type: str = Field(default="AggregateRating", alias="@type")
    ratingValue: float
    reviewCount: int
    bestRating: float = 5.0
    worstRating: float = 1.0


class ProductSchema(SchemaBase):
    """Product schema for e-commerce."""
    type: str = Field(default="Product", alias="@type")
    name: str
    description: Optional[str] = None
    image: Optional[Union[str, List[str]]] = None
    url: Optional[str] = None
    brand: Optional[Dict[str, Any]] = None
    sku: Optional[str] = None
    mpn: Optional[str] = None  # Manufacturer Part Number
    offers: Optional[Union[OfferSchema, Dict[str, Any]]] = None
    aggregateRating: Optional[Union[AggregateRatingSchema, Dict[str, Any]]] = None


class WebPageSchema(SchemaBase):
    """WebPage schema - generic page type."""
    type: str = Field(default="WebPage", alias="@type")
    name: str
    description: Optional[str] = None
    url: Optional[str] = None
    mainEntity: Optional[Dict[str, Any]] = None


class SchemaCollection(BaseModel):
    """Collection of schemas for a single page."""
    schemas: List[Dict[str, Any]] = Field(default_factory=list)
    
    def to_jsonld(self) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Convert to JSON-LD format.
        Returns single schema or array if multiple.
        """
        if len(self.schemas) == 1:
            return self.schemas[0]
        return self.schemas
    
    def to_script_tag(self) -> str:
        """Generate HTML script tag with JSON-LD."""
        import json
        jsonld = self.to_jsonld()
        return f'<script type="application/ld+json">\n{json.dumps(jsonld, indent=2)}\n</script>'
