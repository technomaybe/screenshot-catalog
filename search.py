"""
Screenshot Search CLI
=====================
Interactive command-line tool to search the cataloged screenshot database.

Usage:
    python search.py                        # Interactive REPL
    python search.py "search term"          # Single query, then exit
    python search.py "search term" --limit 20
    python search.py --stats                # Show database statistics
"""

import os
import sys
import argparse
import textwrap

import db
from config import DEFAULT_SEARCH_LIMIT, SNIPPET_LENGTH


SEPARATOR = "─" * 72


def display_results(rows, query: str):
    if not rows:
        print(f"\n  No results found for: {query!r}\n")
        return

    print(f"\n  Found {len(rows)} result(s) for: {query!r}\n")
    print(SEPARATOR)

    for i, row in enumerate(rows, 1):
        print(f"  [{i}]  {row['file_name']}")
        print(f"       Captured : {row['created_time']}")
        print(f"       Indexed  : {row['indexed_time']}")
        print(f"       Path     : {row['file_path']}")

        snippet = row["snippet"] or ""
        if snippet:
            # Wrap long snippets for readability
            wrapped = textwrap.fill(snippet, width=68, initial_indent="       ",
                                    subsequent_indent="       ")
            print(f"       Excerpt  :\n{wrapped}")

        print()

    print(SEPARATOR)


def show_stats():
    stats = db.get_stats()
    print("\n  Database statistics")
    print(SEPARATOR)
    print(f"  Total indexed  : {stats['total']}")
    print(f"  Processed OK   : {stats['processed']}")
    print(f"  Failed (OCR)   : {stats['failed']}")
    print(SEPARATOR + "\n")


def interactive_loop(limit: int):
    print("\n  Screenshot Search  —  type a keyword or phrase to search.")
    print("  Commands:  :stats   :quit / :q   :help\n")
    while True:
        try:
            query = input("  search> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Goodbye.")
            break

        if not query:
            continue
        if query in (":q", ":quit", ":exit"):
            print("  Goodbye.")
            break
        if query == ":stats":
            show_stats()
            continue
        if query == ":help":
            print("\n  Tips:")
            print("    hello world       — finds screenshots containing both words")
            print("    \"hello world\"     — exact phrase search")
            print("    hello OR world    — either word")
            print("    hello*            — prefix wildcard (starts with 'hello')")
            print("    :stats            — show database statistics")
            print("    :quit             — exit\n")
            continue

        rows = db.search(query, limit=limit)
        display_results(rows, query)


def main():
    parser = argparse.ArgumentParser(description="Search cataloged screenshots")
    parser.add_argument("query", nargs="?", help="Search term (omit for interactive mode)")
    parser.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT,
                        help=f"Max results to return (default: {DEFAULT_SEARCH_LIMIT})")
    parser.add_argument("--stats", action="store_true", help="Show database statistics and exit")
    args = parser.parse_args()

    db.initialize_db()

    if args.stats:
        show_stats()
        return

    if args.query:
        rows = db.search(args.query, limit=args.limit)
        display_results(rows, args.query)
    else:
        interactive_loop(limit=args.limit)


if __name__ == "__main__":
    main()
