import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import re
import csv
from openai import OpenAI
from typing import List, Dict, Optional
import time
import random
import os
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

class PricingExtractor:
    def __init__(self, xai_api_key: str = None, your_site_url: str = "https://example.com", your_site_name: str = "PricingExtractor"):
        
        api_key = xai_api_key
        
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",  # The xAI API endpoint
        )
        self.extra_headers = {
            "HTTP-Referer": your_site_url,
            "X-Title": your_site_name,
        }
        
        # Create a session with proper headers to avoid bot detection
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Initialize Playwright browser (will be started when needed)
        self.playwright = None
        self.browser = None
        self.context = None
        
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup Playwright resources"""
        self.close_playwright()
        
    def close_playwright(self):
        """Close Playwright browser and context"""
        if self.context:
            self.context.close()
            self.context = None
        if self.browser:
            self.browser.close()
            self.browser = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None
    
    def init_playwright(self):
        """Initialize Playwright browser if not already done"""
        if not self.playwright:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--disable-blink-features=AutomationControlled'
                ]
            )
            self.context = self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                ignore_https_errors=True
            )
    
    def extract_pricing_content(self, url: str) -> str:
        """Extract content using Playwright for dynamic sites, fallback to requests for static"""
        print(f"📄 Extracting content from: {url}")
        
        # First try with Playwright (handles dynamic content)
        playwright_content = self._extract_with_playwright(url)
        if playwright_content and len(playwright_content) > 100:
            print(f"✅ Playwright extracted {len(playwright_content)} characters")
            return playwright_content
        
        # Fallback to requests for static content
        print("🔄 Playwright failed or insufficient content, trying requests...")
        requests_content = self._extract_with_requests(url)
        if requests_content and len(requests_content) > 100:
            print(f"✅ Requests extracted {len(requests_content)} characters")
            return requests_content
        
        return "Error: Could not extract content with either method"
    
    def _extract_with_playwright(self, url: str) -> str:
        """Extract content using Playwright to handle JavaScript-rendered pages"""
        try:
            self.init_playwright()
            
            page = self.context.new_page()
            
            # Set up request interception to block unnecessary resources
            def route_handler(route):
                if route.request.resource_type in ['image', 'font', 'media']:
                    route.abort()
                else:
                    route.continue_()
            
            page.route('**/*', route_handler)
            
            # Navigate to page with longer timeout for dynamic content
            page.goto(url, wait_until='networkidle', timeout=60000)  # Increased to 60s
            
            # Wait for potential dynamic content to load
            page.wait_for_timeout(3000)
            
            # Try to find and click common "pricing" elements that might be hidden behind interactions
            pricing_selectors = [
                'a[href*="pricing"]',
                'button:has-text("Pricing")',
                '[data-testid*="pricing"]',
                '.pricing-tab',
                '[class*="pricing"] button'
            ]
            
            for selector in pricing_selectors:
                try:
                    element = page.query_selector(selector)
                    if element and element.is_visible():
                        element.click()
                        page.wait_for_timeout(2000)
                        print(f"✅ Clicked pricing element: {selector}")
                        break
                except:
                    continue
            
            # Get the full page content after potential interactions
            content = page.content()
            
            # Parse with BeautifulSoup for cleanup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'iframe']):
                element.decompose()
            
            # Try to find main content areas first
            main_content_selectors = [
                'main',
                '[role="main"]',
                '.main-content',
                '.content',
                '#content',
                '.pricing',
                '.pricing-container',
                '.plan-cards',
                '.price-table'
            ]
            
            body_text = ""
            for selector in main_content_selectors:
                elements = soup.select(selector)
                for element in elements:
                    text = element.get_text(separator=" ", strip=True)
                    if len(text) > len(body_text):
                        body_text = text
            
            # If no specific content area found, use entire body
            if not body_text or len(body_text) < 100:
                body = soup.find('body')
                if body:
                    body_text = body.get_text(separator=" ", strip=True)
            
            page.close()
            return body_text[:50000]  # Cap length
            
        except PlaywrightTimeoutError:
            print(f"❌ Playwright timeout for {url}")
            return ""
        except Exception as e:
            print(f"❌ Playwright error for {url}: {e}")
            return ""
    
    def _extract_with_requests(self, url: str) -> str:
        """Fallback method using requests for static content"""
        try:
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                return f"Error: HTTP {response.status_code}"
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer', 'header']):
                element.decompose()
            
            body = soup.find('body')
            if not body:
                return "Error: No body tag found"
            
            return body.get_text(separator=" ", strip=True)[:50000]
            
        except Exception as e:
            return f"Error: {str(e)}"
    
    def _get_all_website_links(self, domain: str) -> List[str]:
        """Extract all links using Playwright to handle dynamic navigation"""
        all_links = set()
        
        try:
            self.init_playwright()
            
            page = self.context.new_page()
            page.goto(domain, wait_until='networkidle', timeout=30000)
            
            # Wait for dynamic content to load
            page.wait_for_timeout(2000)
            
            # Try to find and extract links from common navigation elements
            navigation_selectors = [
                'nav a',
                'header a',
                '.navbar a',
                '.navigation a',
                '.menu a',
                'footer a'
            ]
            
            for selector in navigation_selectors:
                try:
                    links = page.query_selector_all(selector)
                    for link in links:
                        try:
                            href = link.get_attribute('href')
                            if href and not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                                full_url = urljoin(domain, href)
                                if self._is_valid_url(full_url):
                                    all_links.add(full_url)
                        except:
                            continue
                except:
                    continue
            
            # Also get all links from the page
            all_a_tags = page.query_selector_all('a[href]')
            for tag in all_a_tags:
                try:
                    href = tag.get_attribute('href')
                    if href and not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                        full_url = urljoin(domain, href)
                        if self._is_valid_url(full_url):
                            all_links.add(full_url)
                except:
                    continue
            
            page.close()
            print(f"🔗 Playwright found {len(all_links)} links")
            
        except Exception as e:
            print(f"❌ Playwright link extraction failed: {e}")
            # Fallback to requests method
            all_links.update(self._get_links_alternative_method(domain))
        
        return list(all_links)
    
    def _check_url_exists(self, url: str) -> bool:
        """Check if URL exists using both requests and Playwright (robust version)."""
        headers = {"User-Agent": "Mozilla/5.0"}
    
        # 1. GET request first (most reliable)
        try:
            response = self.session.get(url, timeout=8, allow_redirects=True, headers=headers)
            if response.status_code < 400:
                return True
        except Exception:
            pass
    
        # 2. Playwright fallback for JS-heavy pages
        try:
            self.init_playwright()
            page = self.context.new_page()
            response = page.goto(url, wait_until='domcontentloaded', timeout=15000)
            page.close()
            if response and response.status and response.status < 400:
                return True
        except Exception:
            pass
    
        # 3. HEAD request as last attempt (cheaper, but unreliable)
        try:
            response = self.session.head(url, timeout=5, allow_redirects=True, headers=headers)
            return response.status_code < 400
        except Exception:
            return False
            # Keep all your existing methods below (they remain the same)
    def find_pricing_routes(self, domain: str) -> List[str]:
        """Use AI to intelligently find pricing pages from a domain"""
        print(f"🔍 Using AI to find pricing routes for: {domain}")
        
        # Step 1: Get all possible links from the website
        all_links = self._get_all_website_links(domain)
        print(f"Found {len(all_links)} total links on the website")
        
        # Step 2: Get sitemap links if available
        sitemap_links = self._get_all_sitemap_links(domain)
        print(f"Found {len(sitemap_links)} links from sitemaps")
        
        # Step 3: Always include the homepage for direct pricing analysis
        homepage_links = [domain]
        
        # Combine all links
        all_possible_links = list(set(all_links + sitemap_links + homepage_links))
        print(f"Total unique links to analyze: {len(all_possible_links)}")
        
        if not all_possible_links:
            # If we can't get links, at least try the homepage
            print("No links found, will try homepage analysis only")
            return [domain]
        
        # Step 4: Use AI to identify which links are likely pricing pages
        pricing_urls = self._ai_identify_pricing_links(domain, all_possible_links)
        
        return pricing_urls

    def _get_links_alternative_method(self, domain: str) -> List[str]:
        """Alternative method to get links when main method fails"""
        print("🔄 Using alternative method to get links...")
        links = set()
        
        try:
            # Try with different user agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(domain, headers=headers, timeout=15)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Extract links more aggressively
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '').strip()
                    if href and not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                        full_url = urljoin(domain, href)
                        if self._is_valid_url(full_url):
                            links.add(full_url)
                
                print(f"Alternative method found {len(links)} links")
            
        except Exception as e:
            print(f"❌ Alternative method also failed: {e}")
        
        return list(links)
    
    def _extract_links_from_page(self, soup: BeautifulSoup, domain: str) -> List[str]:
        """Extract all valid links from a page"""
        links = set()
        
        # Try multiple methods to find links
        methods = [
            # Method 1: All <a> tags
            lambda: soup.find_all('a', href=True),
            # Method 2: Navigation elements
            lambda: soup.select('nav a, .nav a, .navbar a, .menu a, [role="navigation"] a'),
            # Method 3: Footer links
            lambda: soup.select('footer a, .footer a'),
            # Method 4: Buttons that might be links
            lambda: soup.select('.button[href], .btn[href], .cta[href]')
        ]
        
        for method in methods:
            try:
                elements = method()
                for element in elements:
                    href = element.get('href', '').strip()
                    if href and not href.startswith(('javascript:', 'mailto:', 'tel:', '#')):
                        full_url = urljoin(domain, href)
                        if self._is_valid_url(full_url):
                            links.add(full_url)
            except Exception as e:
                print(f"⚠️ Error in link extraction method: {e}")
                continue
        
        return list(links)
    
    def _get_all_sitemap_links(self, domain: str) -> List[str]:
        """Extract all links from sitemap(s) with better error handling and loop protection"""
        all_sitemap_links = set()
        processed_sitemaps = set()
        
        try:
            # Find sitemap locations
            sitemap_urls = self._discover_sitemap_urls(domain)
            print(f"Discovered {len(sitemap_urls)} potential sitemap locations")
            
            # Process each sitemap URL with protection against infinite loops
            sitemap_queue = list(sitemap_urls)
            max_iterations = 50  # Safety limit to prevent infinite loops
            iterations = 0
            
            while sitemap_queue and iterations < max_iterations:
                iterations += 1
                sitemap_url = sitemap_queue.pop(0)
                
                if sitemap_url in processed_sitemaps:
                    continue
                    
                if not self._check_url_exists(sitemap_url):
                    continue
                    
                print(f"🔍 Processing sitemap: {sitemap_url}")
                processed_sitemaps.add(sitemap_url)
                
                # Extract links from this sitemap
                links = self._extract_links_from_sitemap(sitemap_url)
                all_sitemap_links.update(links)
                print(f"Found {len(links)} links in {sitemap_url}")
                
                # If it's a sitemap index, process nested sitemaps
                if self._is_sitemap_index(sitemap_url):
                    print("📂 This is a sitemap index, processing nested sitemaps...")
                    nested_sitemaps = self._extract_nested_sitemaps(sitemap_url)
                    
                    # Add new sitemaps to queue for processing
                    for nested_sitemap in nested_sitemaps:
                        if (nested_sitemap not in processed_sitemaps and 
                            nested_sitemap not in sitemap_queue):
                            sitemap_queue.append(nested_sitemap)
            
            if iterations >= max_iterations:
                print("⚠️ Reached maximum sitemap processing iterations (safety limit)")
            
        except Exception as e:
            print(f"❌ Error processing sitemaps: {e}")
        
        return list(all_sitemap_links)
    
    def _discover_sitemap_urls(self, domain: str) -> List[str]:
        """Discover all possible sitemap URLs"""
        sitemap_urls = []
        
        # Common sitemap locations
        common_locations = [
            'sitemap.xml', 'sitemap_index.xml', 'sitemap/sitemap.xml',
            'sitemap.xml.gz', 'sitemap/sitemap_index.xml',
            'wp-sitemap.xml', 'sitemap-index.xml'
        ]
        
        for location in common_locations:
            url = urljoin(domain, location)
            sitemap_urls.append(url)
        
        # Check robots.txt
        robots_url = urljoin(domain, 'robots.txt')
        try:
            response = self.session.get(robots_url, timeout=5)
            if response.status_code == 200:
                for line in response.text.split('\n'):
                    line = line.strip()
                    if line.lower().startswith('sitemap:'):
                        sitemap_url = line.split(':', 1)[1].strip()
                        sitemap_urls.append(sitemap_url)
                        print(f"Found sitemap in robots.txt: {sitemap_url}")
        except:
            pass
        
        return sitemap_urls
    
    def _extract_links_from_sitemap(self, sitemap_url: str) -> List[str]:
        """Extract all links from a sitemap"""
        links = set()
        
        try:
            response = self.session.get(sitemap_url, timeout=10)
            
            # Handle different sitemap formats
            if 'xml' in sitemap_url:
                soup = BeautifulSoup(response.content, 'xml')
                
                # Extract URLs from sitemap
                for loc in soup.find_all('loc'):
                    url = loc.text.strip()
                    if url and self._is_valid_url(url):
                        links.add(url)
                
                # Also check url tags
                for url_tag in soup.find_all('url'):
                    loc = url_tag.find('loc')
                    if loc and loc.text:
                        url = loc.text.strip()
                        if self._is_valid_url(url):
                            links.add(url)
            else:
                # Handle text sitemaps or other formats
                print(f"⚠️ Non-XML sitemap format: {sitemap_url}")
                        
        except Exception as e:
            print(f"❌ Error extracting links from sitemap {sitemap_url}: {e}")
        
        return list(links)
    
    
    def _is_sitemap_index(self, sitemap_url: str) -> bool:
        """Check if sitemap is an index file with better detection"""
        try:
            # First check URL pattern for common index indicators
            if any(pattern in sitemap_url.lower() for pattern in [
                'sitemap_index', 'sitemap-index', 'sitemap.index', 
                'index.xml', 'sitemap.xml/index'
            ]):
                return True
            
            # Then check content
            response = self.session.head(sitemap_url, timeout=5)
            if response.status_code != 200:
                return False
                
            # For large files, check content-type first
            content_type = response.headers.get('content-type', '').lower()
            if 'xml' not in content_type:
                return False
            
            # Only download and check content if necessary
            response = self.session.get(sitemap_url, timeout=5)
            content = response.content.lower()
            
            # Check for sitemap index indicators
            index_indicators = [
                b'sitemapindex',
                b'sitemap_index', 
                b'<sitemapindex',
                b'<sitemapindex>',
                b'sitemap-type="index"'
            ]
            
            return any(indicator in content for indicator in index_indicators)
            
        except Exception as e:
            print(f"⚠️ Error checking if sitemap is index: {e}")
            return False
    
    def _extract_nested_sitemaps(self, sitemap_index_url: str, processed_urls: set = None, depth: int = 0) -> List[str]:
        """Extract nested sitemap URLs from index with protection against infinite loops"""
        if processed_urls is None:
            processed_urls = set()
        
        # Prevent infinite recursion
        if depth > 10:  # Maximum depth limit
            print(f"⚠️ Maximum sitemap depth reached ({depth}), stopping recursion")
            return []
        
        if sitemap_index_url in processed_urls:
            print(f"⚠️ Already processed sitemap: {sitemap_index_url}")
            return []
        
        processed_urls.add(sitemap_index_url)
        nested_sitemaps = []
        
        try:
            response = self.session.get(sitemap_index_url, timeout=10)
            soup = BeautifulSoup(response.content, 'xml')
            
            # Track found URLs to avoid duplicates
            found_urls = set()
            
            # Look for sitemap tags in sitemap index
            sitemap_tags = soup.find_all('sitemap')
            for sitemap_tag in sitemap_tags:
                loc = sitemap_tag.find('loc')
                if loc and loc.text:
                    url = loc.text.strip()
                    if url not in found_urls:
                        found_urls.add(url)
                        nested_sitemaps.append(url)
            
            # Also try alternative format
            if not sitemap_tags:
                loc_tags = soup.find_all('loc')
                for loc_tag in loc_tags:
                    url = loc_tag.text.strip()
                    if (url != sitemap_index_url and 
                        url not in found_urls and 
                        ('sitemap' in url.lower() or '.xml' in url)):
                        found_urls.add(url)
                        nested_sitemaps.append(url)
            
            print(f"📂 Found {len(nested_sitemaps)} nested sitemaps at depth {depth}")
            
            # Recursively process nested sitemaps that are also indexes
            additional_sitemaps = []
            for nested_sitemap in nested_sitemaps[:]:  # Copy list to avoid modification during iteration
                if nested_sitemap not in processed_urls:
                    try:
                        # Check if this nested sitemap is also an index
                        if self._is_sitemap_index(nested_sitemap):
                            print(f"🔍 Nested sitemap is also an index, processing recursively...")
                            deeper_sitemaps = self._extract_nested_sitemaps(
                                nested_sitemap, processed_urls, depth + 1
                            )
                            additional_sitemaps.extend(deeper_sitemaps)
                    except Exception as e:
                        print(f"⚠️ Error checking nested sitemap {nested_sitemap}: {e}")
                        continue
            
            # Add the additional sitemaps found through recursion
            nested_sitemaps.extend(additional_sitemaps)
            
        except Exception as e:
            print(f"❌ Error extracting nested sitemaps from {sitemap_index_url}: {e}")
        
        return list(set(nested_sitemaps))  # Remove duplicates
    
    def _ai_identify_pricing_links(self, domain: str, all_links: List[str]) -> List[str]:
        """Use AI to identify which links are likely pricing pages"""
        print("🤖 Using AI to analyze links and identify pricing pages...")
        
        # Always include homepage for direct pricing analysis
        if domain not in all_links:
            all_links.append(domain)
        
        # Limit the number of links to avoid token limits, but prioritize important ones
        max_links = 400
        if len(all_links) > max_links:
            print(f"Too many links ({len(all_links)}), sampling {max_links} for AI analysis")
            
            # Prioritize links that look promising
            high_priority = [link for link in all_links if any(keyword in link.lower() for keyword in 
                              ['pricing', 'price', 'plan', 'buy', 'subscribe', 'order', 'checkout'])]
            medium_priority = [link for link in all_links if any(keyword in link.lower() for keyword in 
                               ['product', 'feature', 'service', 'solution', 'package', 'tier'])]
            low_priority = [link for link in all_links if link not in high_priority + medium_priority]
            
            # Take high priority first, then medium, then low
            sampled_links = high_priority[:max_links//3]
            remaining = max_links - len(sampled_links)
            sampled_links.extend(medium_priority[:remaining//2])
            remaining = max_links - len(sampled_links)
            sampled_links.extend(low_priority[:remaining])
            
            # Always include homepage
            if domain not in sampled_links:
                sampled_links.append(domain)
                
            all_links = sampled_links
        
        prompt = f"""
        Analyze this list of URLs from {domain} and identify which ones likely contain pricing information.

        URLS TO ANALYZE:
        {json.dumps(all_links, indent=2)}

        IMPORTANT: The homepage ({domain}) might contain pricing directly without needing a separate page.

        Look for:
        1. Obvious pricing pages (/pricing, /plans, /price)
        2. Product pages that include pricing sections
        3. Service pages with plan comparisons
        4. Checkout or order pages
        5. The homepage itself if it shows pricing

        Return JSON with the most likely pricing URLs:

        {{
            "pricing_urls": [
                "https://example.com/pricing",
                "https://example.com",  // homepage if it has pricing
                "https://example.com/product/enterprise"  
            ],
            "confidence_scores": {{
                "https://example.com/pricing": "high",
                "https://example.com": "medium",
                "https://example.com/product/enterprise": "low"
            }}
        }}

        Be comprehensive. Include any URL that might show prices, plans, or subscriptions.
        """
        
        try:
            completion = self.client.chat.completions.create(
                model="grok-code-fast-1",  # Use the Grok model directly
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that analyzes websites to identify pricing pages."},
                    {"role": "user", "content": prompt}
                ],
                timeout=60  # 60 second timeout for AI calls
            )
            
            response_text = completion.choices[0].message.content
            print(f"AI response received: {len(response_text)} characters")
            
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                pricing_urls = result.get('pricing_urls', [])
                
                # Verify URLs exist
                valid_urls = []
                for url in pricing_urls:
                    if self._check_url_exists(url):
                        valid_urls.append(url)
                        print(f"✅ AI identified valid pricing URL: {url}")
                    else:
                        print(f"❌ AI suggested URL doesn't exist: {url}")
                
                print(f"✅ AI identified {len(valid_urls)} valid pricing URLs")
                return valid_urls
            else:
                print("❌ AI returned invalid JSON format")
                # Fallback: return obvious pricing URLs
                return self._fallback_pricing_urls(domain, all_links)
                
        except Exception as e:
            print(f"❌ AI analysis failed: {e}")
            # Fallback to obvious pricing URLs
            return self._fallback_pricing_urls(domain, all_links)
    
    def _fallback_pricing_urls(self, domain: str, all_links: List[str]) -> List[str]:
        """Fallback method when AI fails"""
        print("🔄 Using fallback method to find pricing URLs")
        
        pricing_keywords = ['pricing', 'price', 'plans', 'plan', 'subscribe', 'buy', 'order']
        fallback_urls = []
        
        # Check for obvious pricing URLs
        for link in all_links:
            if any(keyword in link.lower() for keyword in pricing_keywords):
                if self._check_url_exists(link):
                    fallback_urls.append(link)
        
        # Always include homepage
        if domain not in fallback_urls and self._check_url_exists(domain):
            fallback_urls.append(domain)
        
        # Check common paths
        common_paths = ['/pricing', '/price', '/plans', '/plan', '/subscription']
        for path in common_paths:
            url = urljoin(domain, path)
            if self._check_url_exists(url) and url not in fallback_urls:
                fallback_urls.append(url)
        
        print(f"Fallback found {len(fallback_urls)} pricing URLs")
        return fallback_urls
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and belongs to the same domain"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # Avoid non-HTTP URLs and common non-content URLs
            if any(url.lower().endswith(ext) for ext in ['.pdf', '.jpg', '.png', '.gif', '.zip', '.exe', '.css', '.js']):
                return False
                
            return True
        except:
            return False

    def analyze_pricing_with_ai(self, content: str, url: str) -> Dict:
        """Use AI to analyze pricing content and return structured JSON"""
        print("🧠 Analyzing pricing content with AI...")
        
        prompt = f"""
        Analyze this pricing page content from {url} and extract pricing information.

        CONTENT:
        {content}

        Extract to this JSON format:
        {{
          "currency": "usd",
          "plans": [
            {{
              "name": "Plan Name",
              "description": "Plan description",
              "pricing_tiers": [
                {{
                  "type": "recurring",
                  "usage_type": "licensed",
                  "billing_period": "monthly",
                  "price": 0.0,
                  "currency": "usd",
                  "features": ["feature1", "feature2"]
                }}
              ]
            }}
          ]
        }}

        Return ONLY valid JSON.
        """
        
        try:
            completion = self.client.chat.completions.create(
                model="grok-code-fast-1",  # Use the Grok model directly
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that analyzes pricing content and extracts structured pricing information."},
                    {"role": "user", "content": prompt}
                ],
                timeout=60  # 60 second timeout for AI calls
            )
            
            response_text = completion.choices[0].message.content
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {"error": "No valid JSON found", "raw_response": response_text[:500]}
                
        except Exception as e:
            return {"error": f"AI analysis failed: {str(e)}"}

    def get_pricing_data(self, domain: str, name: str) -> Dict:
        """Main method to get pricing data for a domain with safety limits"""
        print(f"\n{'='*70}")
        print(f"🚀 ANALYZING: {name}")
        print(f"🌐 DOMAIN: {domain}")
        print(f"{'='*70}")
        
        # Safety limit for pricing URL discovery
        try:
            pricing_urls = self.find_pricing_routes(domain)
        except Exception as e:
            print(f"❌ Error finding pricing routes: {e}")
            return {
                "name": name,
                "domain": domain,
                "error": f"Error finding pricing routes: {e}",
                "success": False
            }
        
        if not pricing_urls:
            return {
                "name": name,
                "domain": domain,
                "error": "No pricing pages found",
                "success": False
            }
        
        print(f"✅ Found {len(pricing_urls)} potential pricing URLs")
        
        # Limit the number of URLs to try (safety measure)
        # max_urls_to_try = 3  # Reduced from 5 to 3 for faster processing
        # if len(pricing_urls) > max_urls_to_try:
        #     print(f"⚠️ Too many URLs ({len(pricing_urls)}), limiting to first {max_urls_to_try}")
        #     pricing_urls = pricing_urls[:max_urls_to_try]
        
        for i, pricing_url in enumerate(pricing_urls):
            print(f"\n--- Attempt {i+1}/{len(pricing_urls)} ---")
            print(f"🔗 Testing: {pricing_url}")
            
            try:
                content = self.extract_pricing_content(pricing_url)
                
                if "Error" in content or len(content) < 100:
                    print("❌ Content extraction failed or insufficient content")
                    continue
                
                pricing_data = self.analyze_pricing_with_ai(content, pricing_url)
                
                if 'plans' in pricing_data and pricing_data['plans']:
                    print(f"🎉 SUCCESS: Found {len(pricing_data['plans'])} pricing plans!")
                    pricing_data.update({
                        "name": name,
                        "domain": domain,
                        "source_url": pricing_url,
                        "success": True,
                        "content_length": len(content)
                    })
                    return pricing_data
                else:
                    print("❌ No valid pricing data found")
                    
            except Exception as e:
                print(f"❌ Error processing URL {pricing_url}: {e}")
                continue
        
        return {
            "name": name,
            "domain": domain,
            "error": "All URLs failed to yield valid pricing data",
            "attempted_urls": pricing_urls,
            "success": False
        }

def read_urls_from_csv(csv_file_path: str) -> List[Dict]:
    """Read URLs from CSV file"""
    urls = []
    try:
        with open(csv_file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                urls.append({
                    "name": row.get('name', ''),
                    "website": row.get('website', '')
                })
        print(f"📋 Read {len(urls)} URLs from CSV")
    except Exception as e:
        print(f"❌ Error reading CSV file: {e}")
    
    return urls

def load_existing_results(output_file: str) -> Dict:
    """Load existing results from JSON file if it exists"""
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check if this is a checkpoint file with nested structure
            if isinstance(data, dict) and 'results' in data:
                results = data['results']
                print(f"📁 Loaded existing results from checkpoint with {len(results)} items")
            else:
                results = data
                print(f"📁 Loaded existing results with {len(results)} items")
            return results
        except Exception as e:
            print(f"❌ Error loading existing results: {e}")
            return {}
    return {}

def save_checkpoint(output_file: str, results: Dict, processed_count: int, total_count: int):
    """Save current progress as checkpoint"""
    checkpoint_data = {
        "results": results,
        "processed_count": processed_count,
        "total_count": total_count,
        "timestamp": time.time()
    }
    
    checkpoint_file = output_file.replace('.json', '_checkpoint.json')
    try:
        with open(checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(checkpoint_data, f, indent=2, ensure_ascii=False)
        print(f"💾 Checkpoint saved: {processed_count}/{total_count} processed")
        
        # In CI environments, also flush stdout to ensure progress is visible
        if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
            import sys
            sys.stdout.flush()
            
    except Exception as e:
        print(f"❌ Error saving checkpoint: {e}")

def load_checkpoint(output_file: str) -> Optional[Dict]:
    """Load checkpoint if exists"""
    checkpoint_file = output_file.replace('.json', '_checkpoint.json')
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint = json.load(f)
            print(f"🔄 Resuming from checkpoint: {checkpoint['processed_count']}/{checkpoint['total_count']} processed")
            return checkpoint
        except Exception as e:
            print(f"❌ Error loading checkpoint: {e}")
    return None

def get_remaining_urls(all_urls: List[Dict], existing_results: Dict) -> List[Dict]:
    """Get URLs that haven't been processed yet"""
    processed_names = set(existing_results.keys())
    remaining_urls = [url for url in all_urls if url['name'] not in processed_names]
    return remaining_urls

def main():
    # Configuration
    csv_file_path = "urls with titles.csv"
    output_file = 'pricing_results_with_resume.json'
    XAI_API_KEY = os.getenv("OPENROUTER_API_KEY")
    YOUR_SITE_URL = os.getenv("YOUR_SITE_URL")
    YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME")
    
    # Use context manager to ensure proper cleanup
    with PricingExtractor(
        xai_api_key=XAI_API_KEY,
        your_site_url=YOUR_SITE_URL,
        your_site_name=YOUR_SITE_NAME
    ) as extractor:
        
        # Read all URLs from CSV
        all_urls = read_urls_from_csv(csv_file_path)
        if not all_urls:
            print("❌ No URLs found in CSV file!")
            return
          # Load existing results and checkpoint
        existing_results = load_existing_results(output_file)
        checkpoint = load_checkpoint(output_file)
        
        if checkpoint and checkpoint.get('results'):
            # Resume from checkpoint
            results = checkpoint['results']
            processed_count = checkpoint['processed_count']
            remaining_urls = get_remaining_urls(all_urls, results)
            print(f"🔄 Resuming processing: {len(remaining_urls)} URLs remaining")
        else:
            # Start fresh
            results = existing_results
            remaining_urls = get_remaining_urls(all_urls, results)
            processed_count = len(results)
            print(f"🆕 Starting fresh: {len(remaining_urls)} URLs to process")
        
        total_count = len(all_urls)
        successful_count = sum(1 for result in results.values() if result.get('success'))
        
        print(f"\n📊 Progress: {processed_count}/{total_count} processed, {successful_count} successful")
        
        # Process remaining URLs
        for i, item in enumerate(remaining_urls):
            # Don't clear terminal in CI environments to show progress
            if not os.getenv('CI') and not os.getenv('GITHUB_ACTIONS'):
                os.system('clear' if os.name == 'posix' else 'cls')
            
            name = item["name"]
            website = item["website"]
            
            print(f"\n{'#'*80}")
            print(f"🔄 PROCESSING {processed_count + i + 1}/{total_count}: {name}")
            print(f"{'#'*80}")
            
            if not website or website.strip() == "":
                print("❌ Skipping empty URL")
                results[name] = {"error": "Empty URL", "success": False}
                # Save checkpoint even for skipped items
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                continue
            
            try:
                if not website.startswith(('http://', 'https://')):
                    website = 'https://' + website
                
                # Add timeout for individual website processing (10 minutes max per site)
                import signal
                
                def timeout_handler(signum, frame):
                    raise TimeoutError("Website processing timed out after 10 minutes")
                
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(600)  # 10 minutes timeout per website
                
                try:
                    pricing_data = extractor.get_pricing_data(website, name)
                    results[name] = pricing_data
                finally:
                    signal.alarm(0)  # Cancel the alarm
                
                if pricing_data.get('success'):
                    successful_count += 1
                    print(f"✅ SUCCESS: {name}")
                else:
                    print(f"❌ FAILED: {name}")
                
                # Print detailed progress in CI environments
                if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
                    print(f"📊 PROGRESS UPDATE: {processed_count + i + 1}/{total_count} complete, {successful_count} successful")
                    import sys
                    sys.stdout.flush()
                
                # Save checkpoint after each successful processing
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                
                print("⏳ Waiting 2 seconds...")
                time.sleep(2)
                
            except TimeoutError as e:
                error_msg = f"Processing timeout: {str(e)}"
                print(f"⏰ TIMEOUT ERROR: {error_msg}")
                results[name] = {
                    "name": name,
                    "website": website,
                    "error": error_msg,
                    "success": False
                }
                # Save checkpoint even on timeout
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                time.sleep(2)
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                print(f"💥 CRITICAL ERROR: {error_msg}")
                results[name] = {
                    "name": name,
                    "website": website,
                    "error": error_msg,
                    "success": False
                }
                # Save checkpoint even on error
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                time.sleep(2)
                
            except Exception as e:
                error_msg = f"Unexpected error: {str(e)}"
                print(f"💥 CRITICAL ERROR: {error_msg}")
                results[name] = {
                    "name": name,
                    "website": website,
                    "error": error_msg,
                    "success": False
                }
                # Save checkpoint even on error
                save_checkpoint(output_file, results, processed_count + i + 1, total_count)
                time.sleep(2)
        
        # Save final results
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        # Clean up checkpoint file after successful completion
        checkpoint_file = output_file.replace('.json', '_checkpoint.json')
        if os.path.exists(checkpoint_file):
            try:
                os.remove(checkpoint_file)
                print("🧹 Checkpoint file cleaned up")
            except:
                pass
        
        print(f"\n{'='*80}")
        print(f"🎊 PROCESSING COMPLETE!")
        print(f"📊 Total: {len(results)}, ✅ Successful: {successful_count}, ❌ Failed: {len(results) - successful_count}")
        print(f"💾 Final results saved to: {output_file}")
        print(f"{'='*80}")
        
        # Print failed items summary
        failed_items = {name: result for name, result in results.items() if not result.get('success')}
        if failed_items:
            print(f"\n📋 Failed items ({len(failed_items)}):")
            for name, result in failed_items.items():
                print(f"   - {name}: {result.get('error', 'Unknown error')}")
        
        return results
        
    
if __name__ == "__main__":
    import signal
    import sys
    
    def signal_handler(signum, frame):
        print(f"\n⚠️ Script interrupted by signal {signum}. Checkpoint should be saved.")
        print("Run again to resume from where it stopped.")
        sys.exit(1)
    
    # Handle various termination signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        results = main()
    except KeyboardInterrupt:
        print(f"\n⚠️ Script interrupted by user. Checkpoint saved. Run again to resume.")
    except TimeoutError as e:
        print(f"\n⏰ Script timed out: {e}")
        print("Checkpoint saved. Run again to resume from where it stopped.")
    except Exception as e:
        print(f"\n💥 Script crashed with error: {e}")
        print("Checkpoint saved. Run again to resume from where it stopped.")
