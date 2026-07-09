"""Deprecated WAAPI knowledge export helper.

AudioMate no longer writes the legacy monolithic WAAPI knowledge file.
Public WAAPI documentation is not vendored in the open-source branch.
"""


def fetch_docs():
    raise SystemExit(
        "fetch_docs.py is deprecated. Public WAAPI documentation is not vendored "
        "in the open-source branch. Use live Wwise schema queries or authorized "
        "private docs outside public Git."
    )

if __name__ == "__main__":
    fetch_docs()
