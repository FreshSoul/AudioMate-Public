# Third-Party Notices

This document summarizes important third-party licensing and integration boundaries for AudioMate. It is not a substitute for the full license texts of the dependencies used in a particular source checkout or binary release.

## Project License

AudioMate source code is distributed under GPL-3.0-only. See [LICENSE](LICENSE).

## Python Dependencies

Runtime Python dependencies are declared in [requirements.txt](requirements.txt), and development dependencies are declared in [requirements-dev.txt](requirements-dev.txt). Distributors should review the licenses of the exact versions they package.

Notable dependencies include:

| Component | Purpose | Licensing / distribution note |
|---|---|---|
| PyQt6 / PyQt6-WebEngine | Desktop GUI and embedded web view | PyQt6 wheels are commonly offered under GPL or a commercial license from Riverbank Computing. AudioMate uses GPL-3.0-only for the open-source tree to stay on a GPL-compatible path. If a distributor wants a non-GPL AudioMate build, they must confirm a separate PyQt commercial license or replace the Qt binding with a compatible alternative. |
| waapi-client | Wwise Authoring API client | Used to communicate with a locally running Wwise Authoring instance. Check the installed package license before redistribution. |
| openai / anthropic / mcp / httpx | LLM provider and MCP integrations | These libraries do not grant access to any model service; users must provide their own credentials and comply with each service's terms. |
| librosa / pyloudnorm / soundfile / numpy / pandas | Audio analysis and document/data handling | Include the exact dependency license texts in binary distributions. |
| python-reapy | REAPER bridge support | Installed into the generated REAPER Python runtime by [scripts/prepare_reaper_runtime.py](scripts/prepare_reaper_runtime.py). Include its license when bundling the generated runtime. |
| psutil | Process/runtime support inside the generated REAPER runtime | Installed as a transitive dependency of `python-reapy`; include its license when bundling the generated runtime. |

## Generated REAPER Python Runtime

The source repository must not vendor `runtime/reaper-python/`. That directory is generated locally by:

```powershell
python scripts/prepare_reaper_runtime.py
```

The script downloads the official Python 3.11 embeddable package from python.org and installs `python-reapy` into that runtime. The generated directory contains third-party binaries and packages, including Python DLLs and site-packages, and is treated as a build artifact.

Packaged releases may either:

- bundle the generated `runtime/reaper-python/` directory inside the application package, or
- publish it as a separate release asset and document where users should place it, or
- let users generate it locally by running [scripts/prepare_reaper_runtime.py](scripts/prepare_reaper_runtime.py).

If a release bundles the generated runtime, the release must include the relevant third-party license texts, including the Python Software Foundation license for the embeddable Python package and the licenses for installed packages such as `python-reapy`, `psutil`, and `typing_extensions`.

## Wwise Boundary

AudioMate integrates with Audiokinetic Wwise through WAAPI. This repository does not include Wwise, the Wwise SDK, Wwise project files, or copied Audiokinetic official documentation. Users need their own Wwise installation and must comply with Audiokinetic's license terms.

The open-source tree intentionally keeps `src/llm/waapi_docs/` limited to project-owned rules and an empty/public index. Do not commit copied Wwise Help, SDK CHM, Public Library pages, customer projects, or private schemas to this repository.

## REAPER Boundary

AudioMate can control Cockos REAPER through the Reaper Control Plugin and `python-reapy`. This repository does not include REAPER. Users need their own REAPER installation and must comply with Cockos REAPER license terms.

Plugins are executable Python code. Only install plugins from sources you trust, and review write-capable tools before enabling them.