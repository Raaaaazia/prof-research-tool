import requests
import pandas as pd
import json
from datetime import datetime
from urllib.parse import quote
from typing import Optional
import time
import random
import certifi 
import urllib3

def load_list_from_file(filename: str) -> list[str]:
    with open(filename, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

UNIVERSITIES_TO_SCAN = load_list_from_file("uni.txt")
VERTIV_KEYWORDS = load_list_from_file("kw.txt")

YOUR_EMAIL = "aamirraazia@gmail.com"
orcid_cache = {}  # global cache for ORCID lookups

def make_api_request(url: str, headers: dict, max_retries: int = 5) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                delay = (2 ** attempt) + random.uniform(0, 1) 
                print(f"  -> Waiting {delay:.1f} seconds before retry {attempt + 1}...")
                time.sleep(delay)

            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"  -> Rate limited. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                continue
            
            if response.status_code == 200:
                return response.json()
            
            elif response.status_code == 403:
                print(f"  -> 403 Forbidden. Possibly rate limit or missing email in headers")
                print(f"  -> Response: {response.text[:200]}...")
                time.sleep(5)
                continue
            
            elif response.status_code == 404:
                print(f"  -> 404 Not Found. URL might be incorrect: {url}")
                return None
            
            else:
                print(f"  -> HTTP {response.status_code}: {response.text[:200]}...")
                
        except requests.exceptions.RequestException as e:
            print(f"  -> Network error on attempt {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                print("  -> All retry attempts failed.")
                return None
            time.sleep(2)
    
    return None

def enrich_with_orcid(orcid_id: str) -> dict:
    if orcid_id in orcid_cache:
        return orcid_cache[orcid_id]

    headers = {
        "Accept": "application/json",
        "User-Agent": f"Academic Research Tool/1.0 (mailto:{YOUR_EMAIL})"
    }
    url = f"https://pub.orcid.org/v3.0/{orcid_id}"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"[ORCID] {orcid_id} => Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()

            # Email
            email = None
            emails = data.get("person", {}).get("emails", {}).get("email", [])
            for e in emails:
                if e.get("visibility") == "PUBLIC":
                    email = e.get("email")
                    break

            # Department
            department = None
            employment_summaries = data.get("activities-summary", {}).get("employments", {}).get("employment-summary", [])
            for emp in employment_summaries:
                dept = emp.get("department-name")
                if dept:
                    department = dept
                    break  # Use the first one found

            result = {
                "Email": email,
                "Department": department
            }
            orcid_cache[orcid_id] = result
            return result
        else:
            print(f"[ORCID] Failed for {orcid_id}: {response.text[:200]}")

    except Exception as e:
        print(f"[ORCID] Exception for {orcid_id}: {e}")

    return {}

def get_institution_id(institution_name: str) -> Optional[str]:
    print(f"-> Finding OpenAlex ID for: {institution_name}...")
    
    headers = {
        'User-Agent': f'Academic Research Tool/1.0 (mailto:{YOUR_EMAIL})',
        'Accept': 'application/json'
    }
    
    search_terms = [
        institution_name,
        institution_name.replace("University", "").strip(),
        institution_name.split()[0]
    ]
    
    for search_term in search_terms:
        safe_name = quote(search_term)
        url = f"https://api.openalex.org/institutions?search={safe_name}&per_page=10"
        
        print(f"  -> Trying search term: '{search_term}'")
        data = make_api_request(url, headers)
        
        if data and data.get('results'):
            for institution in data['results']:
                inst_name = institution.get('display_name', '').lower()
                if institution_name.lower() in inst_name or inst_name in institution_name.lower():
                    institution_id = institution['id'].split('/')[-1] if '/' in institution['id'] else institution['id']
                    print(f"  -> Found match: {institution['display_name']} (ID: {institution_id})")
                    return institution_id
            
            institution = data['results'][0]
            institution_id = institution['id'].split('/')[-1] if '/' in institution['id'] else institution['id']
            print(f"  -> Using best match: {institution['display_name']} (ID: {institution_id})")
            return institution_id
    
    print(f"  -> WARNING: No institution found for '{institution_name}'.")
    return None

def find_authors_by_works(keyword: str, institution_id: str, university_name: str) -> list:
    print(f"  -> Searching works for keyword '{keyword}' at institution {institution_id}...")
    
    headers = {
        'User-Agent': f'Academic Research Tool/1.0 (mailto:{YOUR_EMAIL})',
        'Accept': 'application/json'
    }
    
    safe_keyword = quote(keyword)
    works_url = f"https://api.openalex.org/works?filter=institutions.id:I{institution_id}&search={safe_keyword}&per_page=50"
    
    data = make_api_request(works_url, headers)
    if not data or not data.get('results'):
        return []
    
    authors_dict = {}
    for work in data['results']:
        for authorship in work.get('authorships', []):
            author = authorship.get('author', {})
            if author and author.get('id'):
                author_id = author['id']
                if author_id not in authors_dict:
                    author_institution = university_name
                    
                    for institution in authorship.get('institutions', []):
                        if institution.get('id') and f"I{institution_id}" in institution['id']:
                            author_institution = institution.get('display_name', university_name)
                            break
                    
                    doi = work.get("doi")
                    title = work.get("title", "")
                    if doi:
                        paper_url = f"https://doi.org/{doi}"
                    elif title:
                        search_query = quote(title)
                        paper_url = f"https://scholar.google.com/scholar?q={search_query}"
                    else:
                        paper_url = work.get("id", "").replace("https://openalex.org/", "https://openalex.org/works/")

                    orcid_id = author.get('orcid')
                    enriched = enrich_with_orcid(orcid_id) if orcid_id else {}

                    authors_dict[author_id] = {
                        "OpenAlex_ID": author_id,
                        "Full_Name": author.get('display_name', 'Unknown'),
                        "Institution": author_institution,
                        "Email": enriched.get("Email"),
                        "Department": enriched.get("Department"),
                        "ORCID": orcid_id,
                        "Matched_Keyword": keyword,
                        "Works_Count": 0,
                        "Cited_By_Count": 0,
                        "Recent_Work_Title": work.get('title', 'Unknown'),
                        "DOI": doi,
                        "Paper_URL": paper_url,
                    }
    
    author_details = []
    for author_id, author_data in list(authors_dict.items())[:20]:
        time.sleep(0.5)
        author_url = f"https://api.openalex.org/authors/{author_id}"
        detailed_data = make_api_request(author_url, headers)
        
        if detailed_data:
            last_known_inst = detailed_data.get('last_known_institution', {})
            if last_known_inst and last_known_inst.get('display_name'):
                author_data["Institution"] = last_known_inst['display_name']
            
            author_data.update({
                "Works_Count": detailed_data.get('works_count', 0),
                "Cited_By_Count": detailed_data.get('cited_by_count', 0)
            })
        
        author_details.append(author_data)
    
    return author_details

def find_authors_direct(keyword: str, institution_id: str, university_name: str) -> list:
    print(f"  -> Direct author search for keyword '{keyword}'...")
    
    headers = {
        'User-Agent': f'Academic Research Tool/1.0 (mailto:{YOUR_EMAIL})',
        'Accept': 'application/json'
    }
    
    safe_keyword = quote(keyword)
    url = f"https://api.openalex.org/authors?filter=last_known_institution.id:I{institution_id}&search={safe_keyword}&per_page=25"
    
    data = make_api_request(url, headers)
    if not data or not data.get('results'):
        return []
    
    authors = []
    for author in data['results']:
        institution_name = university_name
        last_known_inst = author.get('last_known_institution', {})
        if last_known_inst and last_known_inst.get('display_name'):
            institution_name = last_known_inst['display_name']
        
        orcid_id = author.get('orcid')
        enriched = enrich_with_orcid(orcid_id) if orcid_id else {}

        authors.append({
            "OpenAlex_ID": author.get('id'),
            "Full_Name": author.get('display_name'),
            "Institution": institution_name,
            "Email": enriched.get("Email"),
            "Department": enriched.get("Department") or last_known_inst.get('type'),
            "ORCID": orcid_id,
            "Matched_Keyword": keyword,
            "Works_Count": author.get('works_count', 0),
            "Cited_By_Count": author.get('cited_by_count', 0),
            "Paper_URL": None
        })
    
    return authors

def find_authors(keyword: str, institution_id: str, university_name: str) -> list:
    authors = find_authors_by_works(keyword, institution_id, university_name)
    
    if len(authors) < 5:
        print(f"  -> Trying direct author search as backup...")
        direct_authors = find_authors_direct(keyword, institution_id, university_name)
        
        existing_ids = {a['OpenAlex_ID'] for a in authors}
        for author in direct_authors:
            if author['OpenAlex_ID'] not in existing_ids:
                authors.append(author)
    
    return authors

def find_researchers_with_api(universities: list, keywords: list):
    all_found_authors = []
    
    institution_data = {}
    for uni_name in universities:
        uni_id = get_institution_id(uni_name)
        if uni_id:
            institution_data[uni_name] = uni_id
        time.sleep(1)
    
    print(f"\nFound {len(institution_data)} institutions out of {len(universities)} requested.")
    
    for uni_name, uni_id in institution_data.items():
        print(f"\n=== Processing University: {uni_name} ===")
        for keyword in keywords:
            print(f"Searching for: '{keyword}'")
            authors = find_authors(keyword, uni_id, uni_name)
            if authors:
                print(f"  -> Found {len(authors)} authors for '{keyword}'")
                all_found_authors.extend(authors)
            time.sleep(2)
    
    if not all_found_authors:
        print("No authors found!")
        return None

    df = pd.DataFrame(all_found_authors)
    df_unique = df.drop_duplicates(subset=['OpenAlex_ID']).reset_index(drop=True)
    
    print(f"\nFound a total of {len(df_unique)} unique relevant authors.")
    return df_unique
