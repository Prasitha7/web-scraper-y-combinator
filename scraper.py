"""
Y Combinator Startup Directory Scraper
=======================================
Scrapes 500+ startups from https://www.ycombinator.com/companies
Extracts: Company Name, Batch, Description, Founder Names, LinkedIn URLs

Strategy: Uses Algolia API found in HTML source + enriches with LinkedIn data
"""
import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from transformers import logging
logging.set_verbosity_error()

import requests
import pandas as pd
import time
from typing import List, Dict, Optional
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import urllib.parse
from bs4 import BeautifulSoup
import re
from summarizer import TextSummarizer


class YCombinatorScraper:
    def __init__(self):
        # Algolia credentials extracted from the HTML
        self.algolia_app_id = "45BWZJ1SGC"
        self.algolia_api_key = "MjBjYjRiMzY0NzdhZWY0NjExY2NhZjYxMGIxYjc2MTAwNWFkNTkwNTc4NjgxYjU0YzFhYTY2ZGQ5OGY5NDMxZnJlc3RyaWN0SW5kaWNlcz0lNUIlMjJZQ0NvbXBhbnlfcHJvZHVjdGlvbiUyMiUyQyUyMllDQ29tcGFueV9CeV9MYXVuY2hfRGF0ZV9wcm9kdWN0aW9uJTIyJTVEJnRhZ0ZpbHRlcnM9JTVCJTIyeWNkY19wdWJsaWMlMjIlNUQmYW5hbHl0aWNzVGFncz0lNUIlMjJ5Y2RjJTIyJTVE"
        self.algolia_index = "YCCompany_production"
        self.base_url = f"https://{self.algolia_app_id}-dsn.algolia.net/1/indexes/{self.algolia_index}/query"
        self.yc_base = "https://www.ycombinator.com"
        self.companies_data = []
        
        # Headers for requests
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
    
    def scrape_full_description(self, company_slug):
        url = self.get_company_page_url(company_slug)

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()

            match = re.search(r'data-page="([^"]*)"', response.text)
            if not match:
                return None

            json_str = match.group(1)
            json_str = json_str.replace('&quot;', '"').replace('&amp;', '&')

            page_data = json.loads(json_str)

            company = page_data.get("props", {}).get("company", {})
            return company.get("long_description") or company.get("description")

        except Exception:
            return None

        
    def fetch_companies_batch(self, page=0, hits_per_page=100):
        """Fetch a batch of companies from Algolia API"""
        headers = {
            "X-Algolia-Application-Id": self.algolia_app_id,
            "X-Algolia-API-Key": self.algolia_api_key,
            "Content-Type": "application/json",
            **self.headers
        }
        
        # Query parameters
        payload = {
            "query": "",
            "hitsPerPage": hits_per_page,
            "page": page,
            "tagFilters": ["ycdc_public"]
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            return data
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching page {page}: {e}")
            return None
    
    def scrape_all_companies(self, target_count=500):
        """Scrape companies until target is reached"""
        print(f"\n{'='*60}")
        print(f"🚀 Starting YC Scraper - Target: {target_count} companies")
        print(f"{'='*60}\n")
        
        page = 0
        hits_per_page = 100
        total_available = 0
        
        while len(self.companies_data) < target_count:
            print(f"📥 Fetching page {page + 1}...", end=" ")
            result = self.fetch_companies_batch(page, hits_per_page)
            
            if not result or 'hits' not in result:
                print("❌ No results")
                break
            
            hits = result['hits']
            if not hits:
                print("✅ No more companies")
                break
            
            # Track total available
            if page == 0 and 'nbHits' in result:
                total_available = result['nbHits']
                print(f"(Total in DB: {total_available})")
            
            self.companies_data.extend(hits)
            print(f"✅ Got {len(hits)} companies (Total: {len(self.companies_data)})")
            
            # Stop if we've reached the end
            if len(hits) < hits_per_page or len(self.companies_data) >= target_count:
                break
            
            page += 1
            time.sleep(0.3)  # Respectful rate limiting
        
        # Trim to exact target
        self.companies_data = self.companies_data[:target_count]
        print(f"\n✨ Successfully scraped {len(self.companies_data)} companies!\n")
        return self.companies_data
    
    def get_company_page_url(self, company_slug):
        """Construct URL for individual company page"""
        return f"{self.yc_base}/companies/{company_slug}"
    
    def scrape_linkedin_from_company_page(self, company_slug):
        """
        Scrape founder LinkedIn URLs and names from individual company pages
        Extracts from embedded JSON data in page HTML
        Returns list of {name, linkedin_url} dicts
        """
        url = self.get_company_page_url(company_slug)
        founders_data = []
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            # Extract JSON data embedded in HTML
            # Look for the data-page attribute which contains full company info
            match = re.search(r'data-page="({[^"]*"founders"[^"]*})"', response.text)
            
            if not match:
                # Try alternative pattern - look for all JSON in data-page
                match = re.search(r'data-page="([^"]*)"', response.text)
            
            if match:
                json_str = match.group(1)
                # Unescape HTML entities
                json_str = json_str.replace('&quot;', '"')
                json_str = json_str.replace('&amp;', '&')
                
                try:
                    page_data = json.loads(json_str)
                    # Navigate to company/founders data
                    if 'props' in page_data and 'company' in page_data['props']:
                        company = page_data['props']['company']
                        founders = company.get('founders', [])
                        
                        for founder in founders:
                            founder_name = founder.get('full_name') or founder.get('name', 'N/A')
                            linkedin_url = founder.get('linkedin_url', 'N/A')
                            
                            founders_data.append({
                                'name': founder_name,
                                'linkedin_url': linkedin_url,
                                'title': founder.get('title', 'N/A')
                            })
                except json.JSONDecodeError:
                    pass
            
            # Fallback: parse HTML for LinkedIn links if JSON extraction fails
            if not founders_data:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Find all elements with founder info and LinkedIn URLs
                linkedin_links = soup.find_all('a', href=re.compile(r'linkedin\.com'))
                
                processed_urls = set()
                for link in linkedin_links:
                    linkedin_url = link.get('href')
                    if linkedin_url and linkedin_url not in processed_urls:
                        processed_urls.add(linkedin_url)
                        
                        # Try to find founder name near the link
                        founder_name = 'N/A'
                        
                        # Check parent elements for text
                        parent = link.find_parent()
                        for _ in range(3):  # Go up max 3 levels
                            if parent:
                                text = parent.get_text(strip=True)
                                # Look for capitalized name pattern
                                words = text.split()
                                if len(words) >= 2:
                                    # Take first two capitalized words as name
                                    name_parts = []
                                    for word in words:
                                        if word[0].isupper() and len(name_parts) < 2:
                                            name_parts.append(word)
                                    if name_parts:
                                        founder_name = ' '.join(name_parts)
                                        break
                                parent = parent.find_parent()
                        
                        if founder_name != 'N/A' and founder_name:
                            founders_data.append({
                                'name': founder_name,
                                'linkedin_url': linkedin_url,
                                'title': 'N/A'
                            })
            
            return founders_data
            
        except Exception as e:
            return []
    
    def search_linkedin_google(self, founder_name, company_name):
        """
        Use Google to find founder LinkedIn URL
        Returns LinkedIn URL or None
        """
        # Construct Google search query
        query = f'"{founder_name}" "{company_name}" site:linkedin.com/in'
        google_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(google_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse for LinkedIn URLs
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                href = link['href']
                if 'linkedin.com/in/' in href:
                    # Extract clean LinkedIn URL
                    match = re.search(r'(https?://[^/]*linkedin\.com/in/[^/&?]+)', href)
                    if match:
                        return match.group(1)
            
            return None
            
        except Exception as e:
            return None
    
    def enrich_with_linkedin(self, method='api', max_workers=3):
        """
        Enrich founder data with LinkedIn URLs
        method: 'api' (from YC data), 'scrape' (scrape individual pages), or 'both'
        """
        print(f"\n{'='*60}")
        print(f"🔍 Enriching with LinkedIn URLs (method: {method})")
        print(f"{'='*60}\n")
        
        enriched_count = 0
        
        if method in ['api', 'both']:
            # First, collect LinkedIn URLs already in API data
            print("📊 Processing API data for existing LinkedIn URLs...")
            for company in tqdm(self.companies_data, desc="API enrichment"):
                founders = company.get('founders', [])
                if not isinstance(founders, list):
                    founders = [founders] if founders else []
                
                for founder in founders:
                    if isinstance(founder, dict) and founder.get('linkedin_url') and founder.get('linkedin_url') != 'N/A':
                        enriched_count += 1
        
        if method in ['scrape', 'both']:
            # Scrape individual company pages for LinkedIn data
            print("\n🌐 Scraping company pages for founder LinkedIn URLs...")
            
            def scrape_and_update(company):
                slug = company.get('slug')
                if not slug:
                    return 0
                
                founders_from_page = self.scrape_linkedin_from_company_page(slug)
                if founders_from_page:
                    # Update company data with scraped founder info
                    company['founders'] = founders_from_page
                    return len([f for f in founders_from_page if f.get('linkedin_url') != 'N/A'])
                return 0
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(scrape_and_update, company) 
                    for company in self.companies_data
                ]
                
                for future in tqdm(as_completed(futures), total=len(futures), desc="Scraping pages"):
                    try:
                        enriched_count += future.result()
                    except Exception as e:
                        pass
                    time.sleep(0.2)  # Respectful rate limiting
        
        print(f"\n✅ Enriched with {enriched_count} LinkedIn URLs\n")
        return enriched_count
    
    def to_dataframe(self):
        """Convert scraped data to pandas DataFrame with proper structure"""
        rows = []
        
        for company in self.companies_data:
            company_name = company.get('name', 'N/A')
            batch = company.get('batch_name', company.get('batch', 'N/A'))
            description = company.get("summary", company.get("one_liner", "N/A"))
            
            # Extract founders - try multiple field names
            founders = company.get('founders', [])
            if not founders and 'founder' in company:
                founders = [company['founder']]
            
            # Normalize founder data
            normalized_founders = []
            if founders:
                for founder in founders:
                    if isinstance(founder, dict):
                        # Extract various possible field names for founder name
                        founder_name = (
                            founder.get('full_name') or 
                            founder.get('name') or 
                            founder.get('first_name', '')
                        )
                        founder_linkedin = founder.get('linkedin_url', 'N/A')
                        
                        if founder_name and founder_name.strip():
                            normalized_founders.append({
                                'name': founder_name,
                                'linkedin_url': founder_linkedin
                            })
                    elif isinstance(founder, str):
                        # If founder is just a string
                        normalized_founders.append({
                            'name': founder,
                            'linkedin_url': 'N/A'
                        })
            
            if normalized_founders:
                # Create row for each founder
                for founder in normalized_founders:
                    rows.append({
                        'Company Name': company_name,
                        'Batch': batch,
                        'Short Description': description,
                        'Founder Name': founder.get('name', 'N/A').strip(),
                        'Founder LinkedIn URL': founder.get('linkedin_url', 'N/A')
                    })
            else:
                # Company without founder data
                rows.append({
                    'Company Name': company_name,
                    'Batch': batch,
                    'Short Description': description,
                    'Founder Name': 'N/A',
                    'Founder LinkedIn URL': 'N/A'
                })
        
        df = pd.DataFrame(rows)
        return df
    
    def save_to_csv(self, filename='yc_startups.csv'):
        """Save scraped data to CSV"""
        df = self.to_dataframe()
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        
        print(f"{'='*60}")
        print(f"💾 Data saved to: {filename}")
        print(f"{'='*60}")
        print(f"📊 Total rows: {len(df)}")
        print(f"🏢 Unique companies: {df['Company Name'].nunique()}")
        print(f"👥 Total founders: {df[df['Founder Name'] != 'N/A']['Founder Name'].count()}")
        print(f"🔗 LinkedIn URLs found: {df[df['Founder LinkedIn URL'] != 'N/A']['Founder LinkedIn URL'].count()}")
        print(f"📅 Batches covered: {df['Batch'].nunique()}")
        print(f"{'='*60}\n")
        
        return df
    
    def save_raw_json(self, filename='yc_startups_raw.json'):
        """Save raw JSON for backup/debugging"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.companies_data, f, indent=2, ensure_ascii=False)
        print(f"📦 Raw data backup saved to: {filename}\n")


def main():
    """Main execution"""
    print("\n" + "="*60)
    print("🎯 Y Combinator Startup Directory Scraper")
    print("="*60)

    # Initialize scraper
    scraper = YCombinatorScraper()

    # Step 1: Scrape companies from Algolia API
    print("\n[STEP 1] Scraping company data from Algolia...")
    scraper.scrape_all_companies(target_count=500)

    # Step 2: Enrich with LinkedIn & Founder Data
    print("\n[STEP 2] Enriching with founder data from company pages...")
    scraper.enrich_with_linkedin(method='scrape', max_workers=5)

    # Step 2.5: Fetch full descriptions + summarize
    print("\n[STEP 2.5] Fetching full descriptions and summarizing...")
    from summarizer import TextSummarizer
    summarizer = TextSummarizer(model_name="t5-small")


    for company in tqdm(scraper.companies_data, desc="Summarizing"):
        slug = company.get("slug")
        if not slug:
            continue

        full_desc = scraper.scrape_full_description(slug)

        if full_desc:
            company["full_description"] = full_desc
            company["summary"] = summarizer.summarize(full_desc)
        else:
            # Fallback to one-liner if no long description
            company["summary"] = company.get("one_liner", "N/A")

        time.sleep(0.2)  # polite rate limiting

    # Step 3: Save raw JSON backup
    print("\n[STEP 3] Saving raw JSON backup...")
    scraper.save_raw_json()

    # Step 4: Save to CSV
    print("\n[STEP 4] Saving to CSV...")
    df = scraper.save_to_csv()

    # Step 5: Display sample
    print("📋 Sample Data (first 15 rows):\n")
    print(df.head(15).to_string(index=False))

    print("\n✅ Scraping complete! Check yc_startups.csv for full data.")


if __name__ == "__main__":
    main()