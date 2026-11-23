"""Live discovery only; no AI or application generation."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office.discovery import discover
from office.autonomous import config
from office.config import DATA

results = []
for source in config().sources:
    if not source.get('enabled', True):
        continue
    result = discover(source)
    results.append({'source':source, **result})
    print(source['name'], result['state'], result['detail'], flush=True)
DATA.mkdir(exist_ok=True,parents=True)
(DATA/'discovery-probe.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
