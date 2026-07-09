"""Deprecated CHM-to-docs sync entry point.

The open-source branch must not generate or commit third-party WAAPI
documentation extracts. Keep public Git to project-owned rules only, and use
runtime ``ak.wwise.waapi.getSchema`` queries for exact parameter details.
"""


def main() -> int:
    raise SystemExit(
        "CHM documentation syncing is disabled for the open-source branch. "
        "Maintain authorized private docs outside public Git if needed."
    )


if __name__ == "__main__":
    main()
