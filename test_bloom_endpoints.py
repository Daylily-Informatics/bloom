#!/usr/bin/env python3
"""Test all BLOOM endpoints and generate gap analysis."""

import boto3
import requests
import base64
import hashlib
import hmac
import re
import json
import time
from datetime import datetime

# Cognito config
CLIENT_ID = '1glmn93pg49bove54r48t48907'
CLIENT_SECRET = '1ekmqjhi4pq7p5il5t9gd32k873gbihrb4rgi1j9a31s7nbdhv94'
USERNAME = 'john@dyly.bio'
PASSWORD = 'TestPass123!'
BASE_URL = 'http://localhost:8911'

# Delay between requests to avoid rate limiting (seconds)
REQUEST_DELAY = 1.5

def get_cognito_token():
    """Get Cognito auth token."""
    session = boto3.Session(profile_name='lsmc', region_name='us-west-2')
    client = session.client('cognito-idp')
    
    message = USERNAME + CLIENT_ID
    dig = hmac.new(
        CLIENT_SECRET.encode('utf-8'),
        msg=message.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()
    secret_hash = base64.b64encode(dig).decode()
    
    response = client.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow='USER_PASSWORD_AUTH',
        AuthParameters={
            'USERNAME': USERNAME,
            'PASSWORD': PASSWORD,
            'SECRET_HASH': secret_hash
        }
    )
    return response['AuthenticationResult']['IdToken']

def get_routes_from_main():
    """Extract all routes from main.py."""
    with open('main.py', 'r') as f:
        content = f.read()
    
    routes = []
    pattern = r'@app\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']'
    for match in re.finditer(pattern, content, re.IGNORECASE):
        method = match.group(1).upper()
        path = match.group(2)
        routes.append((method, path))
    return sorted(routes, key=lambda x: x[1])

def test_endpoint(session, method, path):
    """Test a single endpoint and return result."""
    url = f"{BASE_URL}{path}"
    
    # Skip paths with parameters
    if '{' in path:
        return {'status': 'SKIP', 'reason': 'Has path params', 'template': None}
    
    try:
        if method == 'GET':
            resp = session.get(url, timeout=10, allow_redirects=False)
        elif method == 'POST':
            resp = session.post(url, timeout=10, allow_redirects=False)
        else:
            return {'status': 'SKIP', 'reason': f'Method {method}', 'template': None}
        
        # Check response
        status_code = resp.status_code
        content = resp.text[:2000] if resp.text else ''
        
        # Detect template type
        template = None
        if 'modern/' in content or 'bloom_modern.css' in content:
            template = 'MODERN'
        elif 'legacy/' in content or 'bloom_header.html' in content or 'static/skins/' in content or '/static/legacy/' in content:
            template = 'LEGACY'
        elif status_code == 302 or status_code == 303:
            location = resp.headers.get('Location', '')
            template = f'REDIRECT:{location[:50]}'
        elif status_code == 401 or status_code == 403:
            template = 'AUTH_REQUIRED'
        elif 'application/json' in resp.headers.get('Content-Type', ''):
            template = 'JSON_API'
        
        return {
            'status': status_code,
            'template': template,
            'content_length': len(content),
            'content_preview': content[:200].replace('\n', ' ')[:100]
        }
    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)[:50], 'template': None}

def main():
    print("Getting Cognito token...")
    token = get_cognito_token()
    print(f"✓ Got token")
    
    # Create session with auth cookie
    session = requests.Session()
    session.cookies.set('id_token', token)
    
    print("\nExtracting routes from main.py...")
    routes = get_routes_from_main()
    print(f"✓ Found {len(routes)} routes")
    
    print("\nTesting endpoints...")
    results = []
    for method, path in routes:
        result = test_endpoint(session, method, path)
        result['method'] = method
        result['path'] = path
        results.append(result)
        status = result.get('status', 'UNKNOWN')
        template = result.get('template', 'UNKNOWN')
        print(f"  {method:6} {path:40} -> {status} ({template})")
    
    # Save results
    with open('endpoint_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n✓ Results saved to endpoint_results.json")

if __name__ == '__main__':
    main()

