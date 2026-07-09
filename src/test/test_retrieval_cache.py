"""Regression tests for WAAPI doc retriever runtime caches."""

import json
import os
import sys
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(TEST_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.llm.retrieval import WaapiDocRetriever


with tempfile.TemporaryDirectory() as docs_dir:
    index_path = os.path.join(docs_dir, "_index.json")
    doc_path = os.path.join(docs_dir, "ak.test.md")
    with open(index_path, "w", encoding="utf-8") as handle:
        json.dump([
            {
                "uri": "ak.test",
                "filename": "ak.test.md",
                "description": "Test doc",
            }
        ], handle)
    with open(doc_path, "w", encoding="utf-8") as handle:
        handle.write("# ak.test\n\nArguments Schema\n")

    retriever = WaapiDocRetriever(docs_dir=docs_dir, api_key="old", base_url="http://old")
    retriever._doc_excerpt_cache["ak.test"] = "cached"
    retriever._embeddings = {"ak.test": [1.0]}
    retriever._embeddings_ready = True
    retriever._tfidf_ready = True
    retriever._idf = {"test": 1.0}
    retriever._doc_tfidf = {"ak.test": {"test": 1.0}}
    retriever._last_init_signature = "stale"

    retriever.configure(api_key="new", base_url="http://new")

    assert retriever._doc_excerpt_cache == {}
    assert retriever._embeddings == {}
    assert retriever._embeddings_ready is False
    assert retriever._tfidf_ready is False
    assert retriever._idf == {}
    assert retriever._doc_tfidf == {}
    assert retriever._last_init_signature is None

    missing_path = os.path.join(docs_dir, "missing.md")
    retriever._doc_paths["ak.missing"] = missing_path
    assert retriever._get_doc_excerpt("ak.missing") == ""
    assert "ak.missing" not in retriever._doc_excerpt_cache

    with open(missing_path, "w", encoding="utf-8") as handle:
        handle.write("now available")
    assert retriever._get_doc_excerpt("ak.missing") == "now available"
    assert retriever._doc_excerpt_cache["ak.missing"] == "now available"

print("test_retrieval_cache: OK")
