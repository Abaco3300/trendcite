from pathlib import Path

import yaml

p = Path(".irmya/infrastructure/DEPLOYMENT_STATE.yaml")
d = yaml.safe_load(p.read_text(encoding="utf-8"))
assert d["production"]["foundation_status"] == "DEPLOYED_DARK"
assert d["production"]["active"] is False
assert d["production"]["activation_authorized"] is False
assert d["production"]["queues_bound"] is False
assert d["production"]["hyperdrive_bound"] is False
print("TC_P008_YAML_VALIDATION_PASS")
