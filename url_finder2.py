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
        self.initial_found_urls = set()
        self.estimated_total = 0
        
        # Final results
        self.found_subdomains = set()
        self.found_subdirectories = set()
        self.found_pages = set()
        self.visited_urls = set()
        self.crawl_queue = deque()
        
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
        """URL से base domain extract करता है"""
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

    def initial_scan_for_count(self):
        """Initial scan करके URLs का count निकालता है"""
        print("🔍 Initial scanning शुरू कर रहे हैं...")
        print("📊 URLs की गिनती कर रहे हैं...")
        
        # Main page को scan करें
        print(f"   🌐 Main page scanning: {self.url}")
        html_content = self.get_page_content(self.url)
        if not html_content:
            print("   ❌ Main page access नहीं हो सका")
            return False
            
        # Main page के links
        main_links = self.extract_links_from_page(self.url, html_content)
        self.initial_found_urls.update(main_links)
        self.initial_found_urls.add(self.url)
        
        print(f"   📍 Main page से {len(main_links)} links मिले")
        
        # Sample pages को scan करें (better estimate के लिए)
        sample_size = min(15, len(main_links))
        sample_links = list(main_links)[:sample_size]
        
        print(f"   🔬 Sample scanning ({sample_size} pages)...")
        
        total_new_links = 0
        successful_samples = 0
        
        for i, link in enumerate(sample_links):
            print(f"      📄 Sample {i+1}/{sample_size}: {link[:60]}...")
            content = self.get_page_content(link, timeout=8)
            if content:
                new_links = self.extract_links_from_page(link, content)
                # Only count new links that we haven't seen before
                new_links = [l for l in new_links if l not in self.initial_found_urls]
                total_new_links += len(new_links)
                self.initial_found_urls.update(new_links)
                successful_samples += 1
                
                if len(new_links) > 0:
                    print(f"         ➕ {len(new_links)} नए links मिले")
        
        # Estimate calculation
        if successful_samples > 0:
            avg_links_per_page = total_new_links / successful_samples
            remaining_pages = len(main_links) - sample_size
            estimated_additional = int(avg_links_per_page * remaining_pages * 0.7)  # Conservative estimate
            self.estimated_total = len(self.initial_found_urls) + estimated_additional
        else:
            self.estimated_total = len(self.initial_found_urls)
        
        return True

    def classify_url(self, url):
        """URL को classify करता है"""
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
                if any(path.lower().endswith(ext) for ext in ['.html', '.htm', '.php', '.asp', '.jsp', '.py', '.pdf', '.doc']):
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

    def find_subdomains_dns(self):
        """DNS के through subdomains find करता है"""
        print("🔍 DNS subdomains check कर रहे हैं...")
        
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
        
        # Concurrent checking with limited workers
        found_count = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_subdomain = {executor.submit(check_subdomain, sub): sub for sub in common_subdomains}
            
            for future in as_completed(future_to_subdomain):
                result = future.result()
                if result:
                    self.found_subdomains.add(result)
                    found_count += 1
                    print(f"   ✅ Found subdomain: {result}")
        
        print(f"   📊 Total DNS subdomains found: {found_count}")

    def controlled_crawl(self):
        """Controlled crawling latest-first order में"""
        print("🕷️ Controlled crawling शुरू कर रहे हैं...")
        
        # Initial URLs को queue में add करें (latest first order)
        sorted_urls = sorted(list(self.initial_found_urls), reverse=True)
        for url in sorted_urls:
            self.crawl_queue.append(url)
        
        crawl_count = 0
        
        print(f"📋 Crawling queue: {len(self.crawl_queue)} URLs")
        print(f"🎯 Target: {self.max_pages} pages maximum")
        
        while self.crawl_queue and crawl_count < self.max_pages:
            current_url = self.crawl_queue.popleft()  # FIFO for systematic crawling
            
            if current_url in self.visited_urls:
                continue
            
            crawl_count += 1
            self.visited_urls.add(current_url)
            
            print(f"🔄 Crawling ({crawl_count}/{self.max_pages}): {current_url[:70]}...")
            
            # URL को classify करें
            self.classify_url(current_url)
            
            # Page content get करें
            content = self.get_page_content(current_url, timeout=8)
            if content:
                new_links = self.extract_links_from_page(current_url, content)
                # Filter out already visited/queued URLs
                new_links = [l for l in new_links if l not in self.visited_urls 
                           and l not in self.crawl_queue]
                
                if new_links:
                    # Add to queue (latest first)
                    for link in reversed(sorted(new_links)):
                        self.crawl_queue.appendleft(link)
                    print(f"   ➕ {len(new_links)} नए links queue में add किए")
            
            # Progress update every 20 pages
            if crawl_count % 20 == 0:
                remaining = len(self.crawl_queue)
                print(f"   📊 Progress: {crawl_count} crawled, {remaining} in queue")
        
        print(f"🏁 Crawling completed: {crawl_count} pages crawled")

    def print_initial_results(self):
        """Initial scan के results print करता है"""
        print("\n" + "="*80)
        print("📊 INITIAL SCAN RESULTS")
        print("="*80)
        
        print(f"🔍 Currently found URLs: {len(self.initial_found_urls)}")
        print(f"📈 Estimated total URLs: {self.estimated_total}")
        print(f"⚙️ Your max pages limit: {self.max_pages}")
        
        if self.estimated_total > self.max_pages:
            print(f"\n⚠️  WARNING: Estimated URLs ({self.estimated_total}) exceed your limit ({self.max_pages})")
            print(f"🔄 Only latest {self.max_pages} URLs will be crawled (newest first)")
        else:
            print(f"\n✅ Estimated URLs ({self.estimated_total}) are within your limit ({self.max_pages})")

    def analyze_with_preview(self):
        """Preview के साथ analysis करता है"""
        print(f"🌐 Smart Website Analysis: {self.url}")
        print(f"📍 Domain: {self.domain}")
        print(f"🏗️ Base Domain: {self.base_domain}")
        print("="*80)
        
        # Step 1: Initial scan
        if not self.initial_scan_for_count():
            print("❌ Initial scan failed")
            return
        
        # Step 2: Show preview results
        self.print_initial_results()
        
        # Step 3: User decision
        print(f"\n❓ Analysis Options:")
        print(f"   1. Continue with full crawling (recommended)")
        print(f"   2. Show only current found URLs")
        print(f"   3. Cancel analysis")
        
        try:
            choice = input(f"\nEnter your choice (1-3): ").strip()
        except KeyboardInterrupt:
            print("\n❌ Analysis cancelled by user")
            return
        
        if choice == '3':
            print("❌ Analysis cancelled by user")
            return
        elif choice == '2':
            # Show only initial results
            self.show_initial_urls_only()
            return
        elif choice != '1':
            print("❌ Invalid choice. Analysis cancelled.")
            return
        
        print(f"\n🚀 Full analysis शुरू कर रहे हैं...")
        
        # Step 4: DNS subdomains
        self.find_subdomains_dns()
        print()
        
        # Step 5: Full crawling
        self.controlled_crawl()
        print()
        
        # Step 6: Final results
        self.print_detailed_results()

    def show_initial_urls_only(self):
        """केवल initial scan के URLs show करता है"""
        print("\n" + "="*80)
        print("📊 INITIAL SCAN URLs")
        print("="*80)
        
        # Quick classification
        temp_subdomains = set()
        temp_subdirectories = set()
        temp_pages = set()
        
        for url in self.initial_found_urls:
            parsed = urlparse(url)
            domain = parsed.netloc
            path = parsed.path.rstrip('/')
            
            if domain != self.domain and self.base_domain in domain:
                temp_subdomains.add(domain)
            elif path:
                if any(path.lower().endswith(ext) for ext in ['.html', '.htm', '.php', '.asp', '.jsp', '.py']):
                    temp_pages.add(url)
                else:
                    temp_subdirectories.add(path.lstrip('/'))
        
        print(f"🔗 Subdomains ({len(temp_subdomains)}):")
        for subdomain in sorted(temp_subdomains):
            print(f"   ├── https://{subdomain}")
        
        print(f"\n📁 Subdirectories ({len(temp_subdirectories)}):")
        for subdir in sorted(temp_subdirectories)[:20]:
            print(f"   ├── {self.url}/{subdir}")
        if len(temp_subdirectories) > 20:
            print(f"   └── ... और {len(temp_subdirectories) - 20} directories")
        
        print(f"\n📄 Pages ({len(temp_pages)}):")
        for page in sorted(temp_pages)[:20]:
            print(f"   ├── {page}")
        if len(temp_pages) > 20:
            print(f"   └── ... और {len(temp_pages) - 20} pages")

    def print_detailed_results(self):
        """Final detailed results print करता है"""
        print("="*80)
        print("📊 FINAL ANALYSIS RESULTS")
        print("="*80)
        
        print(f"\n🏠 Main Website: {self.url}")
        print(f"🌐 Full Domain: {self.domain}")
        print(f"🏗️ Base Domain: {self.base_domain}")
        print(f"📊 Pages Crawled: {len(self.visited_urls)}")
        print(f"⏱️  Analysis Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Subdomains results
        print(f"\n🔗 SUBDOMAINS FOUND ({len(self.found_subdomains)}):")
        if self.found_subdomains:
            for subdomain in sorted(self.found_subdomains):
                print(f"   ├── https://{subdomain}")
                print(f"   │   └── Type: Subdomain")
        else:
            print("   ❌ कोई subdomains नहीं मिले")
        
        # Subdirectories with levels
        subdirs_by_level = defaultdict(list)
        for subdir in self.found_subdirectories:
            level = len([p for p in subdir.split('/') if p])
            subdirs_by_level[level].append(subdir)
        
        print(f"\n📁 SUBDIRECTORIES/FOLDERS FOUND ({len(self.found_subdirectories)}):")
        if self.found_subdirectories:
            for level in sorted(subdirs_by_level.keys()):
                print(f"\n   📂 Level {level} Directories ({len(subdirs_by_level[level])}):")
                for subdir in sorted(subdirs_by_level[level])[:15]:
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
                if page.endswith(('.html', '.htm')):
                    pages_by_type['HTML'].append(page)
                elif page.endswith('.php'):
                    pages_by_type['PHP'].append(page)
                elif page.endswith('.pdf'):
                    pages_by_type['PDF'].append(page)
                else:
                    pages_by_type['Other'].append(page)
            
            for page_type, pages in pages_by_type.items():
                if pages:
                    print(f"\n   📝 {page_type} Pages ({len(pages)}):")
                    for page in sorted(pages)[:10]:
                        print(f"      ├── {page}")
                        print(f"      │   └── Type: {page_type} Page")
                    if len(pages) > 10:
                        print(f"      └── ... और {len(pages) - 10} pages")
        else:
            print("   ❌ कोई specific pages नहीं मिले")
        
        # Summary
        all_found = len(self.found_subdomains) + len(self.found_subdirectories) + len(self.found_pages)
        
        print(f"\n📈 SUMMARY:")
        print(f"   • Total Subdomains: {len(self.found_subdomains)}")
        print(f"   • Total Subdirectories: {len(self.found_subdirectories)}")
        print(f"   • Total Pages Found: {len(self.found_pages)}")
        print(f"   • Total URLs Crawled: {len(self.visited_urls)}")
        print(f"   • Total Unique Locations: {all_found}")

def main():
    print("🕷️  SMART WEBSITE ANALYZER")
    print("📊 Preview → User Choice → Latest-First Crawling")
    print("="*80)
    
    # User input
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
        analyzer.analyze_with_preview()
        
        # Save results option
        save_option = input("\n💾 Results को file में save करना चाहते हैं? (y/n): ").lower()
        if save_option == 'y':
            filename = f"website_analysis_{analyzer.base_domain.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(f"Website Analysis Report\n")
                    f.write(f"URL: {analyzer.url}\n")
                    f.write(f"Domain: {analyzer.domain}\n")
                    f.write(f"Analysis Time: {datetime.now()}\n\n")
                    
                    f.write(f"SUBDOMAINS ({len(analyzer.found_subdomains)}):\n")
                    for subdomain in sorted(analyzer.found_subdomains):
                        f.write(f"  - https://{subdomain}\n")
                    
                    f.write(f"\nSUBDIRECTORIES ({len(analyzer.found_subdirectories)}):\n")
                    for subdir in sorted(analyzer.found_subdirectories):
                        f.write(f"  - {analyzer.url}/{subdir.lstrip('/')}\n")
                    
                    f.write(f"\nPAGES ({len(analyzer.found_pages)}):\n")
                    for page in sorted(analyzer.found_pages):
                        f.write(f"  - {page}\n")
                
                print(f"📁 Results saved to {filename}")
            except Exception as e:
                print(f"❌ File save error: {e}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Analysis interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("कृपया valid URL enter करें।")

if __name__ == "__main__":
    main()
