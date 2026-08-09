"""
Checks whether every scene in script.json has a corresponding entry in
clip_manifest.json. Writes "complete=true" or "complete=false" to
GITHUB_OUTPUT so the workflow can decide whether to proceed to
assembly/upload, or stop here and wait for the next run (after a
credit top-up) to finish the job.
"""

import os
import json

script_path = os.environ.get("SCRIPT_OUTPUT_PATH", "script.json")
manifest_path = os.environ.get("MANIFEST_OUTPUT_PATH", "clip_manifest.json")
github_output = os.environ.get("GITHUB_OUTPUT")

complete = False

if os.path.exists(script_path) and os.path.exists(manifest_path):
    with open(script_path) as f:
        script = json.load(f)
    with open(manifest_path) as f:
        manifest = json.load(f)

    needed_ids = {s["id"] for s in script["scenes"]}
    have_ids = {c["scene_id"] for c in manifest}

    complete = needed_ids.issubset(have_ids)

    if complete:
        print(f"All {len(needed_ids)} scenes have clips. Proceeding to assembly.")
    else:
        missing = needed_ids - have_ids
        print(f"Video is incomplete - missing clips for: {missing}")
        print("Stopping here. This will resume automatically on the next run.")
else:
    print("script.json or clip_manifest.json not found - nothing to assemble yet.")

if github_output:
    with open(github_output, "a") as f:
        f.write(f"complete={'true' if complete else 'false'}\n")
