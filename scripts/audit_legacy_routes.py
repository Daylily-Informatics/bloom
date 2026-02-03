#!/usr/bin/env python3
"""Audit script to find routes using legacy templates without /legacy/ prefix."""
import re

with open('main.py', 'r') as f:
    content = f.read()
    lines = content.split('\n')

# Find all route definitions and their template usage
current_route = None
current_route_line = 0
issues = []

for i, line in enumerate(lines, 1):
    # Check for route decorator
    route_match = re.search(r'@app\.(get|post)\s*\(\s*["\']([^"\']+)["\']', line)
    if route_match:
        current_route = route_match.group(2)
        current_route_line = i
    
    # Check for legacy template usage
    if 'get_template("legacy/' in line and current_route:
        # Check if route has /legacy/ prefix
        if not current_route.startswith('/legacy'):
            template_match = re.search(r'get_template\("legacy/([^"]+)"', line)
            template = template_match.group(1) if template_match else "unknown"
            issues.append({
                'route': current_route,
                'route_line': current_route_line,
                'template': template,
                'template_line': i
            })

print("Routes using legacy templates WITHOUT /legacy/ prefix:")
print("=" * 70)
for issue in issues:
    print(f"Line {issue['route_line']}: {issue['route']}")
    print(f"  -> uses legacy/{issue['template']} (line {issue['template_line']})")
    print()

print(f"\nTotal: {len(issues)} routes need review")

