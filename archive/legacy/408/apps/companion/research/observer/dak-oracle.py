"""Use DAK's existing extraction dependency, without a second demo decoder.

Run with cs2-demo-format/python's frozen environment (demoparser2 0.42.0).
Only explicit public fixture inputs belong in the reproducible experiment.
"""
import importlib.metadata
import json
import sys
from demoparser2 import DemoParser

assert importlib.metadata.version("demoparser2") == "0.42.0"
events = DemoParser(sys.argv[1]).parse_event("player_death")
rows = json.loads(events[["tick", "attacker_steamid", "user_steamid"]].to_json(orient="records"))
with open(sys.argv[2], "x", encoding="utf8") as output:
    json.dump(rows, output)
print(json.dumps({"parser": "demoparser2@0.42.0", "kills": len(rows)}))
