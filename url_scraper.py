import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import dns.resolver
from collections import defaultdict
import os
from urllib.robotparser import RobotFileParser

class AdvancedWebsiteAnalyzer:
    def __init__(self, url, max_depth=3, max_pages=500):
        self.url = url.rstrip('/')
        self.domain = self.extract_domain(url)
        self.base_domain = self.get_base_domain(self.domain)
        self.max_depth = max_depth
        self.max_pages = max_pages
        
        self.found_subdomains = set()
        self.found_subdirectories = set()
        self.all_internal_links = set()
        self.visited_pages = set()
        self.to_visit = set([self.url])
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Categories for better organization
        self.directory_categories = defaultdict(list)

    def extract_domain(self, url):
        """URL से domain extract करता है"""
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')

    def get_base_domain(self, domain):
        """Base domain निकालता है (जैसे python.org from docs.python.org)"""
        parts = domain.split('.')
        if len(parts) >= 2:
            return '.'.join(parts[-2:])
        return domain

    def is_valid_url(self, url):
        """Check करता है कि URL valid है या नहीं"""
        try:
            parsed = urlparse(url)
            return bool(parsed.netloc) and bool(parsed.scheme)
        except:
            return False

    def should_crawl_url(self, url):
        """Check करता है कि URL को crawl करना चाहिए या नहीं"""
        if not self.is_valid_url(url):
            return False
            
        parsed = urlparse(url)
        
        # Skip non-HTML files
        skip_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.gif', '.css', '.js', 
                          '.xml', '.zip', '.tar', '.gz', '.mp4', '.mp3', '.avi']
        if any(url.lower().endswith(ext) for ext in skip_extensions):
            return False
            
        # Skip external domains (but allow subdomains)
        if self.base_domain not in parsed.netloc:
            return False
            
        return True

    def crawl_website(self):
        """Website को systematically crawl करता है"""
        print("🕷️ Website crawling शुरू कर रहे हैं...")
        print(f"📊 Max depth: {self.max_depth}, Max pages: {self.max_pages}")
        
        depth = 0
        current_level = set([self.url])
        
        while current_level and depth < self.max_depth and len(self.visited_pages) < self.max_pages:
            print(f"\n🔍 Depth {depth + 1} crawling... ({len(current_level)} URLs)")
            next_level = set()
            
            # Process current level URLs
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_to_url = {executor.submit(self.crawl_single_page, url): url 
                               for url in current_level if url not in self.visited_pages}
                
                for future in as_completed(future_to_url):
                    url = future_to_url[future]
                    try:
                        links = future.result()
                        if links:
                            next_level.update(links)
                        self.visited_pages.add(url)
                        print(f"   ✅ Crawled: {url}")
                    except Exception as e:
                        print(f"   ❌ Error crawling {url}: {str(e)[:50]}...")
                        self.visited_pages.add(url)
            
            # Filter next level URLs
            current_level = {url for url in next_level 
                           if url not in self.visited_pages and self.should_crawl_url(url)}
            depth += 1
            
            time.sleep(0.5)  # Be respectful to the server

    def crawl_single_page(self, url):
        """Single page को crawl करता है"""
        try:
            response = self.session.get(url, timeout=10, allow_redirects=True)
            if response.status_code != 200:
                return []
                
            soup = BeautifulSoup(response.content, 'html.parser')
            links = []
            
            # सभी links find करें
            for link in soup.find_all('a', href=True):
                href = link['href']
                full_url = urljoin(url, href)
                
                if self.should_crawl_url(full_url):
                    links.append(full_url)
                    self.all_internal_links.add(full_url)
            
            return links
            
        except Exception as e:
            return []

    def analyze_links(self):
        """सभी links को analyze करके subdomains और subdirectories find करता है"""
        print("\n🔍 Links analyze कर रहे हैं...")
        
        for url in self.all_internal_links:
            parsed = urlparse(url)
            
            # Subdomain check
            if parsed.netloc != self.domain and self.base_domain in parsed.netloc:
                self.found_subdomains.add(parsed.netloc)
            
            # Subdirectory analysis
            if parsed.netloc == self.domain or parsed.netloc.endswith('.' + self.base_domain):
                path = parsed.path.strip('/')
                if path:
                    # Full path को add करें
                    self.found_subdirectories.add(url)
                    
                    # Path को categorize करें
                    path_parts = path.split('/')
                    if len(path_parts) >= 1:
                        category = path_parts[0]
                        self.directory_categories[category].append(url)

    def find_additional_subdomains(self):
        """Additional subdomains find करता है"""
        print("\n🔍 Additional subdomains ढूंध रहे हैं...")
        
        common_subdomains = [
            'www', 'mail', 'ftp', 'blog', 'shop', 'store', 'news', 'support',
            'help', 'forum', 'api', 'docs', 'cdn', 'static', 'images', 'img',
            'media', 'admin', 'login', 'secure', 'app', 'mobile', 'm', 'test',
            'dev', 'staging', 'demo', 'portal', 'client', 'download', 'files',
            'wiki', 'community', 'learn', 'tutorial', 'guide', 'help'
        ]
        
        def check_subdomain(subdomain):
            try:
                full_subdomain = f"{subdomain}.{self.base_domain}"
                
                # Skip if already found
                if full_subdomain in self.found_subdomains:
                    return None
                    
                # DNS check
                dns.resolver.resolve(full_subdomain, 'A')
                
                # HTTP check
                for protocol in ['https', 'http']:
                    test_url = f"{protocol}://{full_subdomain}"
                    try:
                        response = self.session.head(test_url, timeout=5, allow_redirects=True)
                        if response.status_code < 400:
                            return full_subdomain
                    except:
                        continue
                        
            except:
                pass
            return None
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            results = executor.map(check_subdomain, common_subdomains)
            
        for result in results:
            if result:
                self.found_subdomains.add(result)
                print(f"   ✅ Found subdomain: {result}")

    def categorize_directories(self):
        """Directories को categories में organize करता है"""
        categories = {
            'Documentation': ['tutorial', 'guide', 'docs', 'help', 'faq', 'reference', 'manual'],
            'Versions': [r'\d+\.\d+', r'v\d+', 'latest', 'stable', 'beta', 'alpha'],
            'Content': ['library', 'howto', 'extending', 'distributing', 'installing'],
            'Navigation': ['index', 'contents', 'genindex', 'search', 'modindex'],
            'Legal': ['license', 'copyright', 'bugs', 'download'],
            'Language': ['en', 'es', 'fr', 'de', 'it', 'ru', 'cn', 'jp', 'kr'],
            'Other': []
        }
        
        categorized = defaultdict(list)
        
        for url in self.found_subdirectories:
            path = urlparse(url).path.strip('/')
            categorized_flag = False
            
            for category, patterns in categories.items():
                if category == 'Other':
                    continue
                    
                for pattern in patterns:
                    if re.search(pattern, path, re.IGNORECASE):
                        categorized[category].append(url)
                        categorized_flag = True
                        break
                if categorized_flag:
                    break
            
            if not categorized_flag:
                categorized['Other'].append(url)
        
        return dict(categorized)

    def analyze(self):
        """Complete analysis करता है"""
        print(f"🌐 Advanced Website Analysis: {self.url}")
        print(f"📍 Domain: {self.domain}")
        print(f"🏠 Base Domain: {self.base_domain}")
        print("="*80)
        
        # Website crawl करें
        self.crawl_website()
        
        # Links analyze करें
        self.analyze_links()
        
        # Additional subdomains find करें
        self.find_additional_subdomains()
        
        # Results print करें
        self.print_detailed_results()

    def print_detailed_results(self):
        """Detailed results print करता है"""
        print("\n" + "="*80)
        print("📊 DETAILED ANALYSIS RESULTS")
        print("="*80)
        
        print(f"\n🏠 Main Website: {self.url}")
        print(f"🌐 Domain: {self.domain}")
        print(f"📊 Total Pages Crawled: {len(self.visited_pages)}")
        print(f"🔗 Total Internal Links Found: {len(self.all_internal_links)}")
        
        # Subdomains results
        print(f"\n🔗 SUBDOMAINS FOUND ({len(self.found_subdomains)}):")
        if self.found_subdomains:
            for subdomain in sorted(self.found_subdomains):
                print(f"   ├── https://{subdomain}")
                print(f"   │   └── Type: Subdomain")
        else:
            print("   ❌ कोई subdomains नहीं मिले")
        
        # Categorized subdirectories
        categorized_dirs = self.categorize_directories()
        total_subdirs = sum(len(urls) for urls in categorized_dirs.values())
        
        print(f"\n📁 SUBDIRECTORIES/PAGES FOUND ({total_subdirs}):")
        
        for category, urls in categorized_dirs.items():
            if urls:
                print(f"\n   📂 {category.upper()} ({len(urls)}):")
                # Show first 10 of each category, then show count
                shown_urls = sorted(urls)[:10]
                for url in shown_urls:
                    parsed_path = urlparse(url).path
                    print(f"      ├── {url}")
                    print(f"      │   └── Path: {parsed_path}")
                
                if len(urls) > 10:
                    print(f"      └── ... और {len(urls) - 10} pages")
        
        # Top-level directories summary
        print(f"\n📈 TOP-LEVEL DIRECTORIES:")
        top_level_dirs = defaultdict(int)
        for url in self.found_subdirectories:
            path = urlparse(url).path.strip('/')
            if path:
                first_dir = path.split('/')[0]
                top_level_dirs[first_dir] += 1
        
        for directory, count in sorted(top_level_dirs.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"   ├── /{directory}/ ({count} pages)")
        
        print(f"\n📈 SUMMARY:")
        print(f"   • Total Subdomains: {len(self.found_subdomains)}")
        print(f"   • Total Subdirectories/Pages: {len(self.found_subdirectories)}")
        print(f"   • Total Sub-sites: {len(self.found_subdomains) + len(self.found_subdirectories)}")
        print(f"   • Pages Crawled: {len(self.visited_pages)}")
        print(f"   • Crawl Depth Used: {self.max_depth}")
        
        # Save results to file
        self.save_results_to_file()

    def save_results_to_file(self):
        """Results को file में save करता है"""
        try:
            filename = f"website_analysis_{self.domain.replace('.', '_')}.txt"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"Website Analysis Results for: {self.url}\n")
                f.write("="*80 + "\n\n")
                
                f.write("SUBDOMAINS:\n")
                for subdomain in sorted(self.found_subdomains):
                    f.write(f"https://{subdomain}\n")
                
                f.write(f"\nSUBDIRECTORIES ({len(self.found_subdirectories)}):\n")
                for url in sorted(self.found_subdirectories):
                    f.write(f"{url}\n")
                
                f.write(f"\nALL INTERNAL LINKS ({len(self.all_internal_links)}):\n")
                for url in sorted(self.all_internal_links):
                    f.write(f"{url}\n")
            
            print(f"\n💾 Results saved to: {filename}")
            
        except Exception as e:
            print(f"❌ Error saving results: {e}")

def main():
    print("🕷️  ADVANCED WEBSITE SUBDOMAIN & SUBDIRECTORY ANALYZER")
    print("="*80)
    
    # User input
    url = input("🌐 Website URL enter करें (with http/https): ").strip()
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Advanced options
    print("\n⚙️  Advanced Options:")
    try:
        max_depth = int(input("🔍 Crawl depth (1-5, default=3): ") or "3")
        max_pages = int(input("📄 Max pages to crawl (50-1000, default=200): ") or "200")
    except:
        max_depth = 3
        max_pages = 200
    
    print(f"\n🚀 Starting analysis with depth={max_depth}, max_pages={max_pages}")
    
    try:
        analyzer = AdvancedWebsiteAnalyzer(url, max_depth=max_depth, max_pages=max_pages)
        analyzer.analyze()
        
    except KeyboardInterrupt:
        print("\n⏹️ Analysis stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        print("कृपया valid URL enter करें।")

if __name__ == "__main__":
    main()
