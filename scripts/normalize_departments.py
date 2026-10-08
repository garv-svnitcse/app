"""Tidy the department names stored on employees.

Older records carry stray spaces and different spellings (" Marketing ", "Mangement "), which
splits people across departments. This script:

  1. trims and collapses spaces,
  2. matches names to registered departments ignoring case,
  3. applies explicit renames you pass with --map for typos it cannot guess.

It only prints the plan unless you add --apply.

    cd backend
    .venv/Scripts/python ../scripts/normalize_departments.py
    .venv/Scripts/python ../scripts/normalize_departments.py --map "Mangement=Management" --map "Founder office=Founder's Office"
    .venv/Scripts/python ../scripts/normalize_departments.py --map ... --apply

Uses MONGO_URL and DB_NAME from backend/.env.
"""
import argparse
import os
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")


def norm(name):
    return " ".join((name or "").split())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", action="append", default=[], metavar="OLD=NEW",
                        help="rename a department (after trimming, case-insensitive), e.g. 'Mangement=Management'")
    parser.add_argument("--apply", action="store_true", help="write the changes (default: only print them)")
    args = parser.parse_args()

    renames = {}
    for item in args.map:
        old, sep, new = item.partition("=")
        if not sep or not norm(old) or not norm(new):
            parser.error(f"--map expects OLD=NEW, got {item!r}")
        renames[norm(old).casefold()] = norm(new)

    db = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=10000)[os.environ["DB_NAME"]]
    registered = {norm(d["name"]).casefold(): norm(d["name"]) for d in db.departments.find({}, {"name": 1})}

    plan = Counter()
    unknown = Counter()
    for user in db.users.find({"department": {"$nin": [None, ""]}}, {"department": 1}):
        current = user["department"]
        target = norm(current)
        target = renames.get(target.casefold(), target)
        target = registered.get(target.casefold(), target)
        if target != current:
            plan[(current, target)] += 1
        if target.casefold() not in registered:
            unknown[target] += 1

    print(f"Database: {os.environ['DB_NAME']}")
    print(f"Registered departments: {', '.join(sorted(registered.values())) or '(none)'}\n")
    if not plan:
        print("No department names need changing.")
    for (old, new), count in sorted(plan.items(), key=lambda kv: kv[0][1]):
        print(f"  {old!r:32} -> {new!r}  ({count} employee{'s' if count != 1 else ''})")
    if unknown:
        print("\nStill not a registered department after this (set them up in Employees > Departments,")
        print("or map them to an existing one with --map):")
        for name, count in unknown.most_common():
            print(f"  {name!r} ({count})")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to write these changes.")
        return
    changed = 0
    for (old, new), _ in plan.items():
        changed += db.users.update_many({"department": old}, {"$set": {"department": new}}).modified_count
    print(f"\nUpdated {changed} employee record(s).")


if __name__ == "__main__":
    main()
