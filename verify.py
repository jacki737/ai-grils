#!/usr/bin/env python3
f = open('E:\\\\ai-girlfriend\\\\app.py', 'r', errors='ignore')
content = f.read()
f.close()
# Check key fixes
print('1. resolve_persona used:', 'resolve_persona(role)' in content)
print('2. /api/history exists:', '@app.get\"/api/history\"' in content)
print('3. /api/due returns messages:', 'return{\"messages\":messages}' in content)