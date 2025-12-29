"""
Schema Generator for the Structured Data Automation Tool.
Generates deterministic schema.org JSON-LD from normalized content.
"""
from typing import List, Dict, Any, Optional

from app.models.content import NormalizedContent, ContentType
from app.models.schema import (
    SchemaCollection,
    ArticleSchema,
    BlogPostingSchema,
    FAQPageSchema,
    FAQQuestion,
    FAQAnswer,
    ServiceSchema,
    ProductSchema,
    BreadcrumbListSchema,
    BreadcrumbListItem,
    OrganizationSchema,
    WebPageSchema,
    PersonSchema,
    ImageObjectSchema,
    OfferSchema,
    AggregateRatingSchema,
)
from app.utils.logger import LayerLogger


class SchemaGenerator:
    """
    Deterministic JSON-LD schema generator.
    
    Principles:
    - No hallucinated values
    - Only output fields supported by available data
    - Google Rich Results compatible
    - Deterministic logic
    """
    
    def __init__(self):
        self.logger = LayerLogger("schema_generator")
    
    def generate(self, content: NormalizedContent) -> SchemaCollection:
        """
        Generate schema.org JSON-LD from normalized content.
        
        Args:
            content: NormalizedContent model
        
        Returns:
            SchemaCollection with all applicable schemas
        """
        self.logger.log_action(
            "schema_generation",
            "started",
            url=content.url,
            content_type=content.content_type.value,
            source_type=content.source_type.value
        )
        
        schemas = []
        
        # Generate primary schema based on content type
        primary_schema = self._generate_primary_schema(content)
        if primary_schema:
            schemas.append(primary_schema)
        
        # Generate FAQ schema if FAQ content present
        if content.faq and len(content.faq) >= 2:
            faq_schema = self._generate_faq_schema(content)
            if faq_schema:
                schemas.append(faq_schema)
        
        # Generate breadcrumb schema if breadcrumbs present
        if content.breadcrumbs and len(content.breadcrumbs) >= 2:
            breadcrumb_schema = self._generate_breadcrumb_schema(content)
            if breadcrumb_schema:
                schemas.append(breadcrumb_schema)
        
        # Generate organization schema if organization info present
        if content.organization_name:
            org_schema = self._generate_organization_schema(content)
            if org_schema:
                schemas.append(org_schema)
        
        self.logger.log_action(
            "schema_generation",
            "completed",
            url=content.url,
            schemas_generated=len(schemas),
            schema_types=[s.get("@type") for s in schemas]
        )
        
        return SchemaCollection(schemas=schemas)
    
    def _generate_primary_schema(self, content: NormalizedContent) -> Optional[Dict[str, Any]]:
        """Generate primary schema based on content type."""
        
        if content.content_type == ContentType.BLOG_POST:
            return self._generate_blog_posting(content)
        
        elif content.content_type == ContentType.ARTICLE:
            return self._generate_article(content)
        
        elif content.content_type == ContentType.SERVICE:
            return self._generate_service(content)
        
        elif content.content_type == ContentType.PRODUCT:
            return self._generate_product(content)
        
        elif content.content_type == ContentType.FAQ:
            # FAQ is handled separately, but add WebPage
            return self._generate_webpage(content)
        
        elif content.content_type in [ContentType.ABOUT, ContentType.CONTACT, ContentType.HOME]:
            return self._generate_webpage(content)
        
        else:
            # Unknown type - generate generic WebPage
            return self._generate_webpage(content)
    
    def _generate_article(self, content: NormalizedContent) -> Dict[str, Any]:
        """Generate Article schema."""
        schema = ArticleSchema(
            headline=self._truncate(content.title, 110),
            description=self._truncate(content.description, 300) if content.description else None,
            image=self._get_primary_image(content),
            author=PersonSchema(name=content.author) if content.author else None,
            datePublished=content.published_date,
            dateModified=content.modified_date,
            mainEntityOfPage=content.url,
        )
        
        return schema.to_jsonld()
    
    def _generate_blog_posting(self, content: NormalizedContent) -> Dict[str, Any]:
        """Generate BlogPosting schema."""
        schema = BlogPostingSchema(
            headline=self._truncate(content.title, 110),
            description=self._truncate(content.description, 300) if content.description else None,
            image=self._get_primary_image(content),
            author=PersonSchema(name=content.author) if content.author else None,
            datePublished=content.published_date,
            dateModified=content.modified_date,
            mainEntityOfPage=content.url,
        )
        
        return schema.to_jsonld()
    
    def _generate_service(self, content: NormalizedContent) -> Dict[str, Any]:
        """Generate Service schema."""
        provider = None
        if content.organization_name:
            provider = OrganizationSchema(
                name=content.organization_name,
                url=self._get_root_url(content.url),
                logo=content.organization_logo,
            )
        
        schema = ServiceSchema(
            name=content.title,
            description=self._truncate(content.description, 300) if content.description else None,
            provider=provider,
            url=content.url,
        )
        
        return schema.to_jsonld()
    
    def _generate_product(self, content: NormalizedContent) -> Dict[str, Any]:
        """
        Generate Product schema with offers and ratings if available.
        
        RULES:
        - Include AggregateRating ONLY if product_rating exists
        - Include offers ONLY if product_offer exists
        - NEVER infer lowPrice/highPrice
        - NEVER infer availability
        - NEVER fabricate reviewCount
        """
        # Compute capabilities if not already done
        if not content.capabilities:
            content.compute_capabilities()
        
        caps = content.capabilities
        field_decisions = []
        
        # Build brand object if available
        brand = None
        if caps and caps.has_brand and content.product_brand:
            brand = {"@type": "Brand", "name": content.product_brand}
            field_decisions.append({
                "field": "brand",
                "included": True,
                "reason": "product_brand extracted from content"
            })
        else:
            field_decisions.append({
                "field": "brand",
                "included": False,
                "reason": "product_brand not available in extracted data"
            })
        
        # Build offers object ONLY if product_offer exists
        offers = None
        if caps and caps.has_price and content.product_offer:
            offer = content.product_offer
            offers = {
                "@type": "Offer",
                "price": offer.price,
                "priceCurrency": offer.currency,
            }
            field_decisions.append({
                "field": "offers.price",
                "included": True,
                "reason": f"Price extracted: {offer.price} {offer.currency}"
            })
            
            # Only include availability if actually extracted
            if caps.has_availability and offer.availability:
                offers["availability"] = f"https://schema.org/{offer.availability}"
                field_decisions.append({
                    "field": "offers.availability",
                    "included": True,
                    "reason": f"Availability extracted: {offer.availability}"
                })
            else:
                field_decisions.append({
                    "field": "offers.availability",
                    "included": False,
                    "reason": "Availability not explicitly extracted, not inferred"
                })
            
            # Seller only if available
            if offer.seller_name:
                offers["seller"] = {"@type": "Organization", "name": offer.seller_name}
                field_decisions.append({
                    "field": "offers.seller",
                    "included": True,
                    "reason": f"Seller extracted: {offer.seller_name}"
                })
        else:
            field_decisions.append({
                "field": "offers",
                "included": False,
                "reason": "No product_offer extracted from content"
            })
        
        # Build aggregate rating ONLY if product_rating exists
        aggregate_rating = None
        if caps and caps.has_rating and content.product_rating:
            rating = content.product_rating
            aggregate_rating = {
                "@type": "AggregateRating",
                "ratingValue": rating.rating_value,
                "bestRating": rating.best_rating,
                "worstRating": rating.worst_rating,
            }
            field_decisions.append({
                "field": "aggregateRating.ratingValue",
                "included": True,
                "reason": f"Rating extracted: {rating.rating_value}"
            })
            
            # Only include reviewCount if actually present (not fabricated)
            if caps.has_reviews and rating.review_count and rating.review_count > 0:
                aggregate_rating["reviewCount"] = rating.review_count
                field_decisions.append({
                    "field": "aggregateRating.reviewCount",
                    "included": True,
                    "reason": f"Review count extracted: {rating.review_count}"
                })
            else:
                field_decisions.append({
                    "field": "aggregateRating.reviewCount",
                    "included": False,
                    "reason": "Review count not available, not fabricated"
                })
        else:
            field_decisions.append({
                "field": "aggregateRating",
                "included": False,
                "reason": "No product_rating extracted from content"
            })
        
        # SKU only if available
        sku = None
        if caps and caps.has_sku and content.product_sku:
            sku = content.product_sku
            field_decisions.append({
                "field": "sku",
                "included": True,
                "reason": f"SKU extracted: {content.product_sku}"
            })
        else:
            field_decisions.append({
                "field": "sku",
                "included": False,
                "reason": "SKU not available in extracted data"
            })
        
        # MPN only if available
        mpn = None
        if caps and caps.has_mpn and content.product_mpn:
            mpn = content.product_mpn
            field_decisions.append({
                "field": "mpn",
                "included": True,
                "reason": f"MPN extracted: {content.product_mpn}"
            })
        else:
            field_decisions.append({
                "field": "mpn",
                "included": False,
                "reason": "MPN not available in extracted data"
            })
        
        # Image - prefer product_images from JSON-LD if available
        image = None
        if caps and caps.has_product_images and content.product_images:
            # Use first JSON-LD image or full array
            image = content.product_images[0] if len(content.product_images) == 1 else content.product_images
            field_decisions.append({
                "field": "image",
                "included": True,
                "reason": f"Image from JSON-LD: {len(content.product_images)} image(s)",
                "source": "jsonld"
            })
        else:
            image = self._get_primary_image(content)
            if image:
                field_decisions.append({
                    "field": "image",
                    "included": True,
                    "reason": "Image from DOM",
                    "source": "dom"
                })
        
        # Log all field decisions
        self.logger.log_action(
            "product_schema_generation",
            "field_decisions",
            decisions=field_decisions,
            capabilities_used=caps.to_dict() if caps else {}
        )
        
        schema = ProductSchema(
            name=content.title,
            description=self._truncate(content.description, 300) if content.description else None,
            image=image,
            url=content.url,
            brand=brand,
            sku=sku,
            mpn=mpn,
            offers=offers,
            aggregateRating=aggregate_rating,
        )
        
        return schema.to_jsonld()
    
    def _generate_webpage(self, content: NormalizedContent) -> Dict[str, Any]:
        """Generate generic WebPage schema."""
        schema = WebPageSchema(
            name=content.title,
            description=self._truncate(content.description, 300) if content.description else None,
            url=content.url,
        )
        
        return schema.to_jsonld()
    
    def _generate_faq_schema(self, content: NormalizedContent) -> Optional[Dict[str, Any]]:
        """Generate FAQPage schema from FAQ content."""
        if not content.faq or len(content.faq) < 2:
            return None
        
        questions = []
        for faq in content.faq:
            if faq.question and faq.answer:
                questions.append(FAQQuestion(
                    name=faq.question,
                    acceptedAnswer=FAQAnswer(text=faq.answer)
                ))
        
        if not questions:
            return None
        
        schema = FAQPageSchema(mainEntity=questions)
        return schema.to_jsonld()
    
    def _generate_breadcrumb_schema(self, content: NormalizedContent) -> Optional[Dict[str, Any]]:
        """Generate BreadcrumbList schema."""
        if not content.breadcrumbs or len(content.breadcrumbs) < 2:
            return None
        
        items = []
        for bc in content.breadcrumbs:
            items.append(BreadcrumbListItem(
                position=bc.position,
                name=bc.name,
                item=bc.url,
            ))
        
        schema = BreadcrumbListSchema(itemListElement=items)
        return schema.to_jsonld()
    
    def _generate_organization_schema(self, content: NormalizedContent) -> Optional[Dict[str, Any]]:
        """Generate Organization schema."""
        if not content.organization_name:
            return None
        
        schema = OrganizationSchema(
            name=content.organization_name,
            url=self._get_root_url(content.url),
            logo=content.organization_logo,
            description=None,  # Don't duplicate page description
        )
        
        return schema.to_jsonld()
    
    def _get_primary_image(self, content: NormalizedContent) -> Optional[str]:
        """Get primary image URL from content."""
        if content.images and len(content.images) > 0:
            # Return first image src
            return content.images[0].src
        return None
    
    def _get_root_url(self, url: str) -> str:
        """Extract root domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max length with ellipsis."""
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."
