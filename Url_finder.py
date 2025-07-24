import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, unquote
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import dns.resolver
from collections import defaultdict, deque
import sys
from datetime import datetime

class SmartWebsiteAnalyzer:
    def __init__(self, url, max_depth=3, max_pages=500):
        self.url = url.rstrip('/')
        self.domain = self.extract_domain(url)
        self.base_domain = self.extract_base_domain(url)
        self.max_depth = max_depth
        self.max_pages = max_pages
        
        # Initial scan results
        self.initial_urls_found = set()
        self.estimated_total = 0
        
        # Final analysis results
        self.found_subdomains = set()
        self.found_subdirectories = set()
        self.found_pages = set()
        self.visited_urls = set()
        self.crawl_count = 0
        
        # Session setup
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
                        if clean_url != url:
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

    def initial_scan(self):
        """Initial scan करके URL count estimate करता है"""
        print("🔍 INITIAL SCAN शुरू कर रहे हैं...")
        print("📊 Website structure analyze कर रहे हैं...")
        
        # Main page को scan करें
        print(f"   🌐 Main page scanning: {self.url}")
        html_content = self.get_page_content(self.url)
        if not html_content:
            print("   ❌ Main page access नहीं हो सका")
            return False
        
        # Main page से links extract करें
        main_page_links = self.extract_links_from_page(self.url, html_content)
        self.initial_urls_found.add(self.url)
        self.initial_urls_found.update(main_page_links)
        
        print(f"   ✅ Main page से {len(main_page_links)} links मिले")
        
        # कुछ sample pages को भी scan करें estimate के लिए
        sample_size = min(5, len(main_page_links))
        sample_links = list(main_page_links)[:sample_size]
        
        total_additional_links = 0
        successful_samples = 0
        
        print(f"   🔍 Sample scanning ({sample_size} pages)...")
        for i, link in enumerate(sample_links):
            print(f"      📄 Sample {i+1}/{sample_size}: {link[:60]}...")
            content = self.get_page_content(link)
            if content:
                sample_links_found = self.extract_links_from_page(link, content)
                new_links = [l for l in sample_links_found if l not in self.initial_urls_found]
                total_additional_links += len(new_links)
                self.initial_urls_found.update(new_links)
                successful_samples += 1
                print(f"         ➕ {len(new_links)} नए links मिले")
        
        # Estimate calculate करें
        if successful_samples > 0:
            avg_new_links_per_page = total_additional_links / successful_samples
            remaining_pages = len(main_page_links) - sample_size
            additional_estimate = avg_new_links_per_page * remaining_pages
            self.estimated_total = len(self.initial_urls_found) + int(additional_estimate)
        else:
            self.estimated_total = len(self.initial_urls_found)
        
        return True

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

    def controlled_crawl(self):
        """Controlled crawling with latest-first approach"""
        print(f"\n🕷️ CONTROLLED CRAWLING शुरू कर रहे हैं...")
        
        # URLs को queue में add करें (latest first order)
        urls_to_crawl = deque(sorted(self.initial_urls_found, reverse=True))
        
        print(f"📋 Crawling queue: {len(urls_to_crawl)} URLs")
        print(f"🎯 Target: {self.max_pages} pages maximum")
        
        while urls_to_crawl and self.crawl_count < self.max_pages:
            # Latest URL ko process करें
            current_url = urls_to_crawl.popleft()
            
            if current_url in self.visited_urls:
                continue
            
            self.crawl_count += 1
            self.visited_urls.add(current_url)
            
            print(f"   🔄 Crawling ({self.crawl_count}/{self.max_pages}): {current_url}")
            
            # URL को classify करें
            self.classify_url(current_url)
            
            # Page content get करके नए links find करें
            content = self.get_page_content(current_url)
            if content:
                new_links = self.extract_links_from_page(current_url, content)
                fresh_links = [l for l in new_links if l not in self.visited_urls and l not in urls_to_crawl]
                
                # नए links को queue के शुरू में add करें (latest first)
                for link in reversed(sorted(fresh_links)):
                    urls_to_crawl.appendleft(link)
                
                if fresh_links:
                    print(f"      ➕ {len(fresh_links)} नए links added to queue")
            
            # Progress update हर 10 pages पर
            if self.crawl_count % 10 == 0:
                print(f"      📊 Progress: {self.crawl_count} completed, {len(urls_to_crawl)} remaining")

    def find_subdomains_dns(self):
        """DNS के through subdomains find करता है"""
        print("🔍 DNS subdomains checking...")
        
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

    def show_initial_results(self):
        """Initial scan के results show करता है"""
        print("\n" + "="*80)
        print("📊 INITIAL SCAN RESULTS")
        print("="*80)
        
        print(f"🌐 Website: {self.url}")
        print(f"📍 Domain: {self.domain}")
        print(f"🏗️ Base Domain: {self.base_domain}")
        print(f"⏰ Scan Time: {datetime.now().strftime('%H:%M:%S')}")
        
        print(f"\n📈 SCAN STATISTICS:")
        print(f"   🔍 Currently found URLs: {len(self.initial_urls_found)}")
        print(f"   📊 Estimated total URLs: {self.estimated_total}")
        print(f"   ⚙️ Your max pages limit: {self.max_pages}")
        
        # Show some sample URLs
        if self.initial_urls_found:
            print(f"\n🔗 SAMPLE URLs FOUND (first 10):")
            sample_urls = sorted(list(self.initial_urls_found))[:10]
            for i, url in enumerate(sample_urls, 1):
                print(f"   {i:2d}. {url}")
            
            if len(self.initial_urls_found) > 10:
                print(f"       ... और {len(self.initial_urls_found) - 10} URLs")

    def get_user_permission(self):
        """User से permission लेता है"""
        print(f"\n{'='*80}")
        
        if self.estimated_total > self.max_pages:
            print(f"⚠️  WARNING:")
            print(f"   📊 Estimated URLs ({self.estimated_total}) > Your limit ({self.max_pages})")
            print(f"   🔄 केवल latest {self.max_pages} URLs crawl होंगे")
            print(f"   📅 Latest से old order में crawling होगी")
        else:
            print(f"✅ GOOD NEWS:")
            print(f"   📊 Estimated URLs ({self.estimated_total}) <= Your limit ({self.max_pages})")
            print(f"   🎯 सभी URLs crawl हो सकते हैं")
        
        print(f"\n❓ क्या आप full analysis continue करना चाहते हैं?")
        decision = input("   Type 'y' for Yes, 'n' for No: ").lower().strip()
        
        return decision == 'y'

    def analyze_with_initial_scan(self):
        """Complete analysis with initial scan"""
        print("🕷️  SMART WEBSITE ANALYZER")
        print("📊 Initial Scan → User Permission → Latest-First Crawling")
        print("="*80)
        
        # Step 1: Initial scan
        if not self.initial_scan():
            print("❌ Initial scan failed")
            return
        
        # Step 2: Show initial results
        self.show_initial_results()
        
        # Step 3: Get user permission
        if not self.get_user_permission():
            print("\n❌ Analysis cancelled by user")
            return
        
        print(f"\n🚀 FULL ANALYSIS शुरू कर रहे हैं...")
        
        # Step 4: DNS subdomains check
        self.find_subdomains_dns()
        
        # Step 5: Controlled crawling
        self.controlled_crawl()
        
        # Step 6: Final results
        self.print_final_results()

    def print_final_results(self):
        """Final detailed results print करता है"""
        print("\n" + "="*80)
        print("📊 FINAL ANALYSIS RESULTS")
        print("="*80)
        
        print(f"\n🏠 Main Website: {self.url}")
        print(f"🌐 Full Domain: {self.domain}")
        print(f"🏗️ Base Domain: {self.base_domain}")
        print(f"⏰ Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
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
                print(f"\n   📂 Level {level} Directories ({len(subdirs_by_level[level])}):")
                for subdir in sorted(subdirs_by_level[level])[:15]:  # Show max 15 per level
                    full_path = f"{self.url}/{subdir.lstrip('/')}"
                    print(f"      ├── {full_path}")
                    print(f"      │   └── Type: Directory/Folder (Level {level})")
                if len(subdirs_by_level[level]) > 15:
                    print(f"      └── ... और {len(subdirs_by_level[level]) - 15} directories")
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
                    # Latest pages पहले show करें
                    sorted_pages = sorted(pages, reverse=True)
                    for page in sorted_pages[:15]:  # Show max 15
                        print(f"      ├── {page}")
                        print(f"      │   └── Type: {page_type} Page")
                    if len(pages) > 15:
                        print(f"      └── ... और {len(pages) - 15} pages")
        else:
            print("   ❌ कोई specific pages नहीं मिले")
        
        # All found URLs summary
        all_urls = set()
        all_urls.update(f"https://{sub}" for sub in self.found_subdomains)
        all_urls.update(f"{self.url}/{subdir.lstrip('/')}" for subdir in self.found_subdirectories)
        all_urls.update(self.found_pages)
        
        print(f"\n🌐 ALL DISCOVERED URLs ({len(all_urls)}):")
        if len(all_urls) <= 30:
            for url in sorted(all_urls, reverse=True):  # Latest first
                print(f"   ├── {url}")
        else:
            # Latest 15 show करें
            sorted_urls = sorted(list(all_urls), reverse=True)
            for url in sorted_urls[:15]:
                print(f"   ├── {url}")
            print(f"   ├── ... (showing latest 15 of {len(all_urls)})")
            # Oldest 5 भी show करें
            for url in sorted_urls[-5:]:
                print(f"   ├── {url}")
        
        print(f"\n📈 SUMMARY:")
        print(f"   • Total Subdomains: {len(self.found_subdomains)}")
        print(f"   • Total Subdirectories: {len(self.found_subdirectories)}")
        print(f"   • Total Pages Found: {len(self.found_pages)}")
        print(f"   • Total URLs Crawled: {len(self.visited_urls)}")
        print(f"   • Total Unique Locations: {len(all_urls)}")
        print(f"   • Initial Estimate vs Actual: {self.estimated_total} vs {len(all_urls)}")

def main():
    print("🕷️  ADVANCED WEBSITE ANALYZER - SUBDOMAINS & DIRECTORIES")
    print("📊 Initial Count → User Permission → Latest-First Analysis")
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
        max_pages = int(input("📄 Maximum pages to crawl (default 100): ") or "100")
    except ValueError:
        max_depth = 3
        max_pages = 100
    
    try:
        # Analyzer create करें और run करें
        analyzer = SmartWebsiteAnalyzer(url, max_depth=max_depth, max_pages=max_pages)
        analyzer.analyze_with_initial_scan()
        
        # Save results option
        save_option = input("\n💾 Results को file में save करना चाहते हैं? (y/n): ").lower()
        if save_option == 'y':
            filename = f"website_analysis_{analyzer.base_domain.replace('.', '_')}.txt"
            print(f"📁 Results would be saved to {filename}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Analysis interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("कृपया valid URL enter करें।")

if __name__ == "__main__":
    main()
