"""Adapters package initialization."""
from app.adapters.html_scraper import HTMLScraper
from app.adapters.wordpress import WordPressAdapter
from app.adapters.shopify import ShopifyAdapter

__all__ = ["HTMLScraper", "WordPressAdapter", "ShopifyAdapter"]
