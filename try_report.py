import os
import sys

import requests

URL = "http://127.0.0.1:8000/reports/upload"


def main():
    if len(sys.argv) < 2:
        print("usage: python try_report.py <pdf path> [word that must not appear ...]")
        return
    path, forbidden = sys.argv[1], sys.argv[2:]
    sys.stdout.reconfigure(encoding="utf-8")

    with open(path, "rb") as f:
        data = f.read()
    try:
        r = requests.post(
            URL,
            files={"file": (os.path.basename(path), data, "application/pdf")},
            timeout=180,
        )
    except requests.exceptions.ConnectionError:
        print("Server is not running. Start it with: uvicorn backend.main:app --reload")
        return

    print(f"file: {path} | HTTP {r.status_code}")
    try:
        d = r.json()
    except ValueError:
        print(r.text)
        return
    if r.status_code != 200:
        print(d.get("detail", d))
        return

    print(f'{d["document_type"]} | {len(d["markers"])} markers\n')
    for m in d["markers"]:
        print(f'{m["name"]:<42}{m["value"]:<10}{m["unit"]:<14}{m["reference_range"]:<22}{m["status"]}')
    print("\nSUMMARY:", d["summary"], "\n")
    for q in d["recommendations"]:
        print("Q:", q)
    if d.get("emergency_notice"):
        print("\nEMERGENCY NOTICE:", d["emergency_notice"])

    hits = [w for w in forbidden if w.lower() in r.text.lower()]
    print("\nleak check:", hits if hits else "none")


main()
