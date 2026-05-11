#!/usr/bin/env python3
import json
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from prospect_pipeline import run_collection


def main():
    project_root = os.path.dirname(CURRENT_DIR)
    result = run_collection('37420', project_root)
    print(json.dumps({'summary': result['summary'], 'top_non_site': result['top_non_site'], 'job_dir': result['config']['job_dir']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
