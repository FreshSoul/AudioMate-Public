import argparse


def update_knowledge(web_content_path: str | None = None) -> None:
    """Deprecated compatibility entry point.

    The old monolithic WAAPI knowledge file has been removed. WAAPI docs now
    live in ``src/llm/waapi_docs/`` with ``_index.json``.
    """
    raise SystemExit(
        "update_knowledge.py is deprecated. Public WAAPI documentation is not vendored "
        "in the open-source branch. Use live Wwise schema queries or authorized "
        "private docs outside public Git."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deprecated WAAPI knowledge refresh helper.")
    parser.add_argument("--web-content", help="Path to the scraped temp_web_content text file.")
    args = parser.parse_args()
    update_knowledge(args.web_content)

