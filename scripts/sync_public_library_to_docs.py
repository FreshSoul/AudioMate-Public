"""Deprecated public-library sync entry point.

The open-source repository must not vendor Audiokinetic documentation copied
from the Public Library, Wwise Help, or SDK CHM. Keep ``src/llm/waapi_docs`` to
project-owned rules only, and use runtime ``ak.wwise.waapi.getSchema`` queries
for exact WAAPI parameter details.

Teams with separate written permission may maintain private documentation
artifacts outside the public branch.
"""


def main() -> int:
    raise SystemExit(
        "Public Library syncing is disabled for the open-source branch. "
        "Use live Wwise WAAPI schema queries or maintain authorized private docs outside public Git."
    )


if __name__ == "__main__":
    main()
