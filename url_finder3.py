import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import dns.resolver
from collections import defaultdict
import sys

class WebsiteAnalyzer:
    def __init__(self, url, max_depth=3, max_pages=500):
        self.url = url.rstrip('/')
        self.domain = self.extract_domain(url)
        self.base_domain = self.extract_base_domain(url)
        self.found_subdomains = set()
        self.found_subdirectories = set()
        self.found_pages = set()
        self.visited_urls = set()
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def extract_domain(self, url):
        """URL से full domain extract करता है"""
        parsed = urlparse(url)
        return parsed.netloc

    def extract_base_domain(self, url):
        """URL से base domain extract करता है (without subdomain)"""
        parsed = urlparse(url)
        domain_parts = parsed.netloc.split('.')
        if len(domain_parts) >= 2:
            return '.'.join(domain_parts[-2:])
        return parsed.netloc

    def is_valid_url(self, url):
        """Check करता है कि URL valid है या नहीं"""
        try:
            parsed = urlparse(url)
            return bool(parsed.netloc) and bool(parsed.scheme)
        except:
            return False

    def get_page_content(self, url, timeout=10):
        """Page का content get करता है"""
        try:
            response = self.session.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"   ❌ Error accessing {url}: {str(e)[:50]}...")
        return None

    def extract_links_from_page(self, url, html_content):
        """Page से सभी links extract करता है"""
        links = set()
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # सभी anchor tags find करें
            for tag in soup.find_all(['a', 'link'], href=True):
                href = tag.get('href', '').strip()
                if href:
                    full_url = urljoin(url, href)
                    if self.is_same_domain(full_url):
                        # Remove fragments and query parameters for classification
                        parsed = urlparse(full_url)
                        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                        if clean_url != url and clean_url not in self.visited_urls:
                            links.add(clean_url)
            
            # Meta redirects भी check करें
            meta_refresh = soup.find('meta', attrs={'http-equiv': 'refresh'})
            if meta_refresh and 'content' in meta_refresh.attrs:
                content = meta_refresh['content']
                url_match = re.search(r'url=(.+)', content, re.IGNORECASE)
                if url_match:
                    redirect_url = urljoin(url, url_match.group(1))
                    if self.is_same_domain(redirect_url):
                        links.add(redirect_url)
                        
        except Exception as e:
            print(f"   ❌ Error parsing {url}: {str(e)[:50]}...")
        
        return links

    def is_same_domain(self, url):
        """Check करता है कि URL same domain का है या नहीं"""
        try:
            parsed = urlparse(url)
            url_domain = parsed.netloc
            return self.base_domain in url_domain or url_domain in self.domain
        except:
            return False

    def classify_url(self, url):
        """URL को classify करता है (subdomain, subdirectory, या page)"""
        parsed = urlparse(url)
        domain = parsed.netloc
        path = parsed.path.rstrip('/')
        
        # Check if it's a subdomain
        if domain != self.domain and self.base_domain in domain:
            self.found_subdomains.add(domain)
            return "subdomain"
        
        # Check if it's a subdirectory or page
        if path:
            path_parts = [part for part in path.split('/') if part]
            if path_parts:
                # If path ends with common file extensions, it's a page
                if any(path.lower().endswith(ext) for ext in ['.html', '.htm', '.php', '.asp', '.jsp', '.py']):
                    self.found_pages.add(url)
                    # Also add its directory
                    if len(path_parts) > 1:
                        dir_path = '/'.join(path_parts[:-1])
                        self.found_subdirectories.add(dir_path)
                    return "page"
                else:
                    # It's a directory
                    self.found_subdirectories.add(path.lstrip('/'))
                    return "subdirectory"
        
        return "page"

    def crawl_website(self, start_url=None, depth=0):
        """Website को crawl करता है"""
        if start_url is None:
            start_url = self.url
            
        if depth > self.max_depth or len(self.visited_urls) >= self.max_pages:
            return
        
        if start_url in self.visited_urls:
            return
            
        self.visited_urls.add(start_url)
        print(f"   🔍 Crawling (depth {depth}): {start_url}")
        
        # Page content get करें
        html_content = self.get_page_content(start_url)
        if not html_content:
            return
        
        # URL को classify करें
        self.classify_url(start_url)
        
        # सभी links extract करें
        links = self.extract_links_from_page(start_url, html_content)
        
        # Recursively crawl found links
        for link in links:
            if len(self.visited_urls) < self.max_pages:
                self.crawl_website(link, depth + 1)
            else:
                break

    def find_subdomains_dns(self):
        """DNS के through subdomains find करता है"""
        print("🔍 DNS से subdomains ढूंध रहे हैं...")
        
        common_subdomains = [
            'www', 'mail', 'ftp', 'blog', 'shop', 'store', 'news',
            'support', 'help', 'forum', 'api', 'docs', 'cdn', 'static',
            'images', 'img', 'media', 'admin', 'login', 'secure',
            'app', 'mobile', 'm', 'test', 'dev', 'staging', 'demo',
            'portal', 'client', 'customer', 'member', 'user', 'status',
            'beta', 'alpha', 'v2', 'download', 'files', 'bugs', 'issues'
        ]
        
        def check_subdomain(subdomain):
            try:
                full_subdomain = f"{subdomain}.{self.base_domain}"
                dns.resolver.resolve(full_subdomain, 'A')
                
                # HTTP request भी भेजें
                for protocol in ['https', 'http']:
                    try:
                        test_url = f"{protocol}://{full_subdomain}"
                        response = self.session.head(test_url, timeout=5, allow_redirects=True)
                        if response.status_code < 400:
                            return full_subdomain
                    except:
                        continue
            except:
                pass
            return None
        
        # Concurrent checking
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_subdomain = {executor.submit(check_subdomain, sub): sub for sub in common_subdomains}
            
            for future in as_completed(future_to_subdomain):
                result = future.result()
                if result:
                    self.found_subdomains.add(result)
                    print(f"   ✅ Found subdomain: {result}")

    def analyze_deep(self):
        """Deep analysis करता है"""
        print(f"🌐 Deep Website Analysis शुरू कर रहे हैं: {self.url}")
        print(f"📍 Domain: {self.domain}")
        print(f"🏗️ Base Domain: {self.base_domain}")
        print(f"🔢 Max Depth: {self.max_depth}, Max Pages: {self.max_pages}")
        print("="*80)
        
        # पहले DNS से subdomains find करें
        self.find_subdomains_dns()
        print()
        
        # फिर website को crawl करें
        print("🕷️ Website crawling शुरू कर रहे हैं...")
        self.crawl_website()
        print()
        
        self.print_detailed_results()

    def print_detailed_results(self):
        """Detailed results print करता है"""
        print("="*80)
        print("📊 DETAILED ANALYSIS RESULTS")
        print("="*80)
        
        print(f"\n🏠 Main Website: {self.url}")
        print(f"🌐 Full Domain: {self.domain}")
        print(f"🏗️ Base Domain: {self.base_domain}")
        
        # Subdomains results
        print(f"\n🔗 SUBDOMAINS FOUND ({len(self.found_subdomains)}):")
        if self.found_subdomains:
            for subdomain in sorted(self.found_subdomains):
                print(f"   ├── https://{subdomain}")
                print(f"   │   └── Type: Subdomain")
        else:
            print("   ❌ कोई subdomains नहीं मिले")
        
        # Subdirectories results with categorization
        subdirs_by_level = defaultdict(list)
        for subdir in self.found_subdirectories:
            level = len([p for p in subdir.split('/') if p])
            subdirs_by_level[level].append(subdir)
        
        print(f"\n📁 SUBDIRECTORIES/FOLDERS FOUND ({len(self.found_subdirectories)}):")
        if self.found_subdirectories:
            for level in sorted(subdirs_by_level.keys()):
                print(f"\n   📂 Level {level} Directories:")
                for subdir in sorted(subdirs_by_level[level]):
                    full_path = f"{self.url}/{subdir.lstrip('/')}"
                    print(f"      ├── {full_path}")
                    print(f"      │   └── Type: Directory/Folder (Level {level})")
        else:
            print("   ❌ कोई subdirectories नहीं मिले")
        
        # Pages found
        print(f"\n📄 PAGES FOUND ({len(self.found_pages)}):")
        if self.found_pages:
            pages_by_type = defaultdict(list)
            for page in self.found_pages:
                if page.endswith('.html') or page.endswith('.htm'):
                    pages_by_type['HTML'].append(page)
                elif page.endswith('.php'):
                    pages_by_type['PHP'].append(page)
                else:
                    pages_by_type['Other'].append(page)
            
            for page_type, pages in pages_by_type.items():
                if pages:
                    print(f"\n   📝 {page_type} Pages ({len(pages)}):")
                    for page in sorted(pages)[:20]:  # Show only first 20
                        print(f"      ├── {page}")
                        print(f"      │   └── Type: {page_type} Page")
                    if len(pages) > 20:
                        print(f"      └── ... और {len(pages) - 20} pages")
        else:
            print("   ❌ कोई specific pages नहीं मिले")
        
        # All found URLs summary
        all_urls = set()
        all_urls.update(f"https://{sub}" for sub in self.found_subdomains)
        all_urls.update(f"{self.url}/{subdir.lstrip('/')}" for subdir in self.found_subdirectories)
        all_urls.update(self.found_pages)
        
        print(f"\n🌐 ALL DISCOVERED URLs ({len(all_urls)}):")
        if len(all_urls) <= 50:
            for url in sorted(all_urls):
                print(f"   ├── {url}")
        else:
            for url in sorted(list(all_urls)[:25]):
                print(f"   ├── {url}")
            print(f"   ├── ... (showing first 25 of {len(all_urls)})")
            for url in sorted(list(all_urls)[-5:]):
                print(f"   ├── {url}")
        
        print(f"\n📈 SUMMARY:")
        print(f"   • Total Subdomains: {len(self.found_subdomains)}")
        print(f"   • Total Subdirectories: {len(self.found_subdirectories)}")
        print(f"   • Total Pages Found: {len(self.found_pages)}")
        print(f"   • Total URLs Crawled: {len(self.visited_urls)}")
        print(f"   • Total Unique Locations: {len(all_urls)}")

def main():
    print("🕷️  ADVANCED WEBSITE ANALYZER - SUBDOMAINS & DIRECTORIES")
    print("="*80)
    
    # User से URL input लें
    url = input("🌐 Website URL enter करें (with http/https): ").strip()
    
    # URL validation
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Advanced options
    print("\n⚙️ Advanced Options:")
    try:
        max_depth = int(input("🔢 Maximum crawl depth (default 3): ") or "3")
        max_pages = int(input("📄 Maximum pages to crawl (default 500): ") or "500")
    except ValueError:
        max_depth = 3
        max_pages = 500
    
    try:
        # Analyzer create करें और run करें
        analyzer = WebsiteAnalyzer(url, max_depth=max_depth, max_pages=max_pages)
        analyzer.analyze_deep()
        
        # Save results option
        save_option = input("\n💾 Results को file में save करना चाहते हैं? (y/n): ").lower()
        if save_option == 'y':
            filename = f"website_analysis_{analyzer.base_domain.replace('.', '_')}.txt"
            # Here you can add file saving logic
            print(f"📁 Results saved to {filename}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Analysis interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("कृपया valid URL enter करें।")

if __name__ == "__main__":
    main()
