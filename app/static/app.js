/**
 * Structured Data Generator - Frontend Application
 * Handles mode selection, form submission, and results display
 */

// State
let currentMode = null;
let lastResult = null;

// DOM Elements
const modeSelection = document.querySelector('.mode-selection');
const modeCards = document.querySelectorAll('.mode-card');
const formSection = document.getElementById('form-section');
const formTitle = document.getElementById('form-title');
const cmsSelectGroup = document.getElementById('cms-select-group');
const disclaimerText = document.getElementById('disclaimer-text');
const generateForm = document.getElementById('generate-form');
const submitBtn = document.getElementById('submit-btn');
const backBtn = document.getElementById('back-btn');
const resultsSection = document.getElementById('results-section');
const errorSection = document.getElementById('error-section');
const newBtn = document.getElementById('new-btn');
const retryBtn = document.getElementById('retry-btn');

// Disclaimers
const DISCLAIMERS = {
    cms: 'For CMS-based generation, API access may be required. Public self-hosted WordPress sites usually do not require authentication. WordPress.com sites may require OAuth connection.',
    html: 'HTML-only generation does not use CMS data and may be less accurate. This mode does not require CMS access and works with any website.',
    ai: 'AI-Enhanced mode uses Claude AI to clean author names, classify article sections, and generate descriptions. This provides the most complete schema output.'
};

// Initialize
document.addEventListener('DOMContentLoaded', init);

function init() {
    // Mode selection handlers
    modeCards.forEach(card => {
        card.addEventListener('click', () => selectMode(card.dataset.mode));
    });

    // Back button
    backBtn.addEventListener('click', showModeSelection);

    // Form submission
    generateForm.addEventListener('submit', handleSubmit);

    // New generation
    newBtn.addEventListener('click', showModeSelection);
    retryBtn.addEventListener('click', showModeSelection);

    // Copy buttons
    document.getElementById('copy-btn').addEventListener('click', () => copyToClipboard('output-json', 'copy-btn'));
    document.getElementById('copy-script-btn').addEventListener('click', () => copyToClipboard('output-script', 'copy-script-btn'));
}

/**
 * Select a generation mode
 */
function selectMode(mode) {
    currentMode = mode;

    // Update card selection
    modeCards.forEach(card => {
        card.classList.toggle('selected', card.dataset.mode === mode);
    });

    // Update form title based on mode
    const titles = {
        cms: 'CMS-Based Generation',
        html: 'HTML-Only Generation',
        ai: 'AI-Enhanced Generation'
    };
    formTitle.textContent = titles[mode] || 'Generate Structured Data';

    // Show/hide CMS selector (only for CMS mode)
    cmsSelectGroup.classList.toggle('hidden', mode !== 'cms');

    // Update disclaimer
    disclaimerText.textContent = DISCLAIMERS[mode];

    // Show form
    modeSelection.classList.add('hidden');
    formSection.classList.remove('hidden');
    resultsSection.classList.add('hidden');
    errorSection.classList.add('hidden');

    // Focus URL input
    document.getElementById('url-input').focus();
}

/**
 * Show mode selection
 */
function showModeSelection() {
    currentMode = null;
    modeCards.forEach(card => card.classList.remove('selected'));

    modeSelection.classList.remove('hidden');
    formSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    errorSection.classList.add('hidden');

    // Reset form
    generateForm.reset();
}

/**
 * Handle form submission
 */
async function handleSubmit(e) {
    e.preventDefault();

    const url = document.getElementById('url-input').value.trim();
    const cmsType = document.getElementById('cms-select').value;

    if (!url) {
        showError('Please enter a valid URL');
        return;
    }

    // Show loading state
    setLoading(true);

    try {
        // AI mode = HTML scraping + AI enhancement
        const isAIMode = currentMode === 'ai';
        const apiMode = isAIMode ? 'html' : currentMode;
        const aiEnhance = isAIMode;

        console.log(`[Schema Generator] Mode: ${currentMode}, API Mode: ${apiMode}, AI Enhance: ${aiEnhance}`);

        const response = await fetch('/api/generate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                mode: apiMode,
                cms_type: cmsType !== 'auto' ? cmsType : null,
                ai_enhance: aiEnhance,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to generate schema');
        }

        const result = await response.json();
        lastResult = result;
        showResults(result);

    } catch (error) {
        showError(error.message);
    } finally {
        setLoading(false);
    }
}

/**
 * Set loading state
 */
function setLoading(loading) {
    submitBtn.disabled = loading;
    submitBtn.querySelector('.btn-text').classList.toggle('hidden', loading);
    submitBtn.querySelector('.btn-loader').classList.toggle('hidden', !loading);
}

/**
 * Show results
 */
function showResults(result) {
    formSection.classList.add('hidden');
    errorSection.classList.add('hidden');
    resultsSection.classList.remove('hidden');

    // Meta info
    const metaHtml = `
        <span class="meta-item">
            <span class="meta-label">Source:</span>
            <span class="meta-value">${formatSource(result.source_used)}</span>
        </span>
        <span class="meta-item">
            <span class="meta-label">Content Type:</span>
            <span class="meta-value">${formatContentType(result.content_type)}</span>
        </span>
        <span class="meta-item">
            <span class="meta-label">Confidence:</span>
            <span class="meta-value">${Math.round(result.confidence * 100)}%</span>
        </span>
        ${result.cms_detected ? `
        <span class="meta-item">
            <span class="meta-label">CMS:</span>
            <span class="meta-value">${result.cms_detected}</span>
        </span>
        ` : ''}
    `;
    document.getElementById('results-meta').innerHTML = metaHtml;

    // Schema types
    const schemaTypes = result.schemas.map(s => s['@type']).filter(Boolean);
    const schemaTypesHtml = schemaTypes.map(type => `
        <span class="schema-tag">
            <span class="schema-tag-icon">${getSchemaIcon(type)}</span>
            ${type}
        </span>
    `).join('');
    document.getElementById('schema-types').innerHTML = schemaTypesHtml;

    // JSON output (the generated schemas)
    document.getElementById('output-json').textContent = JSON.stringify(result.schemas, null, 2);

    // Script tag
    document.getElementById('output-script').textContent = result.script_tag;

    // Debug info
    document.getElementById('debug-content').textContent = JSON.stringify({
        trace_id: result.trace_id,
        url: result.url,
        mode: result.mode,
        cms_detected: result.cms_detected,
        source_used: result.source_used,
        content_type: result.content_type,
        confidence: result.confidence,
    }, null, 2);
}

/**
 * Show error
 */
function showError(message) {
    formSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    errorSection.classList.remove('hidden');

    document.getElementById('error-message').textContent = message;
}

/**
 * Copy to clipboard
 */
async function copyToClipboard(elementId, buttonId) {
    const text = document.getElementById(elementId).textContent;
    const button = document.getElementById(buttonId);

    try {
        await navigator.clipboard.writeText(text);

        // Show copied state
        const originalHtml = button.innerHTML;
        button.classList.add('copied');
        button.innerHTML = '<span class="copy-icon">✓</span> Copied!';

        setTimeout(() => {
            button.classList.remove('copied');
            button.innerHTML = originalHtml;
        }, 2000);

    } catch (err) {
        console.error('Failed to copy:', err);
    }
}

/**
 * Format source for display
 */
function formatSource(source) {
    const sources = {
        'wordpress_rest': 'WordPress REST API',
        'wordpress_rest_authenticated': 'WordPress REST (Auth)',
        'shopify_api': 'Shopify API',
        'html_scraper': 'HTML Scraping',
    };
    return sources[source] || source;
}

/**
 * Format content type for display
 */
function formatContentType(type) {
    const types = {
        'article': 'Article',
        'blog_post': 'Blog Post',
        'service': 'Service',
        'product': 'Product',
        'faq': 'FAQ',
        'about': 'About Page',
        'contact': 'Contact Page',
        'home': 'Home Page',
        'unknown': 'General Page',
    };
    return types[type] || type;
}

/**
 * Get icon for schema type
 */
function getSchemaIcon(type) {
    const icons = {
        'Article': '📰',
        'BlogPosting': '✍️',
        'Service': '🔧',
        'Product': '🛍️',
        'FAQPage': '❓',
        'BreadcrumbList': '🔗',
        'Organization': '🏢',
        'LocalBusiness': '📍',
        'WebPage': '📄',
        'Person': '👤',
    };
    return icons[type] || '📋';
}
