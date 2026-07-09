"""
WAAPI Document Retrieval Module

Provides semantic search over WAAPI function documentation using OpenAI Embeddings API.
Falls back to TF-IDF keyword matching when embeddings are unavailable.
"""

import os
import sys
import json
import math
import hashlib
import re
from collections import Counter

from src.services.web_access import WebAccessError, WebAccessService


def _safe_basename(path: str) -> str:
    return os.path.basename(path) if path else ""


class WaapiDocRetriever:
    """
    Retrieves relevant WAAPI function documentation based on user queries.
    
    Uses OpenAI Embeddings API for semantic search with TF-IDF fallback.
    Caches embeddings to avoid redundant API calls.
    """

    # These docs are always included in retrieval results regardless of query score.
    PINNED_URIS = [
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.set",
        "ak.wwise.core.object.setProperty",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.setReference",
        "ak.wwise.core.object.getAttenuationCurve",
        "ak.wwise.core.object.setStateGroups",
        "ak.wwise.core.object.setStateProperties",
        "ak.wwise.core.object.setAttenuationCurve",
    ]

    def __init__(self, docs_dir=None, api_key=None, base_url=None, embedding_model=None):
        """
        Initialize the retriever.
        
        Args:
            docs_dir: Path to waapi_docs directory. Auto-detected if None.
            api_key: OpenAI-compatible API key for embeddings.
            base_url: API base URL.
            embedding_model: Model name for embeddings (default: text-embedding-3-large).
        """
        if docs_dir is None:
            if hasattr(sys, '_MEIPASS'):
                docs_dir = os.path.join(sys._MEIPASS, 'src', 'llm', 'waapi_docs')
            else:
                docs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'waapi_docs')

        self.docs_dir = docs_dir
        self.api_key = api_key
        self.base_url = base_url
        self.embedding_model = embedding_model or "text-embedding-3-large"
        self.max_cache_bytes = 16 * 1024 * 1024
        self.max_runtime_embedding_bytes = 64 * 1024 * 1024

        # Caches
        self._rules_cache = None
        self._index = None
        self._doc_paths = {}          # uri -> absolute file path
        self._doc_excerpt_cache = {}  # uri -> short excerpt for embeddings
        self._embeddings = {}         # uri -> vector
        self._embeddings_ready = False
        self._tfidf_ready = False
        self._idf = {}                # token -> idf value
        self._doc_tfidf = {}          # uri -> tfidf vector dict
        self._last_init_signature = None
        self._last_init_status = ""
        self._last_retrieval_meta = {}
        self.web_access = WebAccessService()

        # Load index
        self._load_index()

    def clear_runtime_caches(self):
        """Clear derived in-memory search caches without reloading document metadata."""
        self._doc_excerpt_cache = {}
        self._embeddings = {}
        self._embeddings_ready = False
        self._tfidf_ready = False
        self._idf = {}
        self._doc_tfidf = {}
        self._last_init_signature = None

    def configure(self, api_key=None, base_url=None, embedding_model=None):
        updated = False
        if api_key != self.api_key:
            self.api_key = api_key
            updated = True
        if base_url != self.base_url:
            self.base_url = base_url
            updated = True
        if embedding_model and embedding_model != self.embedding_model:
            self.embedding_model = embedding_model
            updated = True
        if updated:
            self.clear_runtime_caches()

    @staticmethod
    def _normalize_base_url(base_url):
        return (base_url or "").strip().rstrip("/").lower()

    def _cache_scope(self):
        return {
            "model": self.embedding_model,
            "base_url": self._normalize_base_url(self.base_url),
        }

    def _current_init_signature(self):
        return (
            self._compute_files_hash(),
            self.embedding_model,
            self._normalize_base_url(self.base_url),
            bool((self.api_key or "").strip()),
        )

    def _disable_embeddings(self, reason):
        self._embeddings = {}
        self._embeddings_ready = False
        print(f"[WaapiDocRetriever] {reason}")

    def _load_index(self):
        """Load _index.json and build lightweight path index."""
        index_path = os.path.join(self.docs_dir, '_index.json')
        if not os.path.exists(index_path):
            print(f"[WaapiDocRetriever] WARNING: _index.json not found at {index_path}")
            self._index = []
            return

        with open(index_path, 'r', encoding='utf-8') as f:
            self._index = json.load(f)

        for entry in self._index:
            filepath = os.path.join(self.docs_dir, entry['filename'])
            if os.path.exists(filepath):
                self._doc_paths[entry['uri']] = filepath

    def _get_doc_path(self, uri: str) -> str:
        return self._doc_paths.get(uri, "")

    def _read_doc_content(self, uri: str) -> str:
        path = self._get_doc_path(uri)
        if not path or not os.path.exists(path):
            return ""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except MemoryError:
            raise
        except Exception as e:
            print(f"[WaapiDocRetriever] Failed to read {_safe_basename(path)}: {e}")
            return ""

    def _get_doc_excerpt(self, uri: str, max_chars: int = 500) -> str:
        cached = self._doc_excerpt_cache.get(uri)
        if cached is not None:
            return cached

        content = self._read_doc_content(uri)
        if not content:
            return ""

        excerpt = content[:max_chars]
        self._doc_excerpt_cache[uri] = excerpt
        return excerpt

    def _get_index_entry(self, uri: str) -> dict:
        for entry in self._index:
            if entry.get("uri") == uri:
                return entry
        return {}

    def _extract_markdown_section(self, content: str, heading: str) -> str:
        if not content or not heading:
            return ""

        pattern = re.compile(
            rf"(^##+\s+{re.escape(heading)}.*?$)(.*?)(?=^##+\s+|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(content)
        if not match:
            return ""
        section = (match.group(1) + match.group(2)).strip()
        return section

    def _extract_official_source_url(self, content: str) -> str:
        if not content:
            return ""

        match = re.search(r"-\s*Source:\s*(https?://\S+)", content, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _infer_official_source_url(self, uri: str) -> str:
        if not uri:
            return ""
        doc_id = uri.strip().lower().replace(".", "_")
        return f"https://www.audiokinetic.com/en/public-library/?source=SDK&id={doc_id}.html"

    def _local_doc_has_parameter_guidance(self, content: str) -> bool:
        if not content:
            return False
        tokens = (
            "Arguments Schema",
            "Arguments",
            "Result Schema",
            "Example",
            "Official Source",
        )
        return any(token in content for token in tokens)

    def _summarize_local_doc(self, uri: str, content: str, max_chars: int = 3200) -> str:
        if not content:
            return ""

        parts = [f"# {uri}"]
        for heading in ("Arguments Schema", "Arguments", "Result Schema", "Result", "Examples", "Example"):
            section = self._extract_markdown_section(content, heading)
            if section and section not in parts:
                parts.append(section)

        source_url = self._extract_official_source_url(content)
        if source_url:
            parts.append("## Official Source\n\n- Source: " + source_url)

        if len(parts) == 1:
            parts.append(content[:max_chars])

        summary = "\n\n".join(part.strip() for part in parts if part.strip())
        return summary[:max_chars]

    def _summarize_web_doc(self, uri: str, fetched: dict, max_chars: int = 1800) -> str:
        if not fetched:
            return ""

        text = (fetched.get("text") or "").strip()
        if not text:
            return ""

        title = (fetched.get("title") or uri).strip()
        source_url = (fetched.get("url") or "").strip()
        parts = [
            f"## Official Web Fallback\n\n- Title: {title}",
        ]
        if source_url:
            parts.append(f"- Source: {source_url}")
        parts.append("\n" + text[:max_chars])
        return "\n".join(parts).strip()

    def _fetch_official_reference(self, uri: str, local_doc: str = "", max_chars: int = 1800) -> str:
        source_url = self._extract_official_source_url(local_doc) or self._infer_official_source_url(uri)
        if not source_url:
            return ""

        try:
            fetched = self.web_access.fetch_webpage(source_url, max_chars=max_chars, timeout=12)
        except WebAccessError as exc:
            print(f"[WaapiDocRetriever] Official doc fetch blocked for {uri}: {exc}")
            return ""
        except Exception as exc:
            print(f"[WaapiDocRetriever] Official doc fetch failed for {uri}: {exc}")
            return ""

        return self._summarize_web_doc(uri, fetched, max_chars=max_chars)

    def retrieve_authoritative_by_uris(self, uris: list[str], include_web_fallback: bool = True) -> str:
        """Return focused WAAPI docs for failed URIs.

        Local synced docs are used first. If a local doc is missing or does not
        contain parameter guidance, optionally fetch the official Audiokinetic
        page and append a compact fallback excerpt.
        """
        result_parts = []
        seen = set()
        for uri in uris or []:
            if not uri or uri in seen:
                continue
            seen.add(uri)
            local_doc = self._read_doc_content(uri)
            local_summary = self._summarize_local_doc(uri, local_doc)
            needs_web_fallback = include_web_fallback and not self._local_doc_has_parameter_guidance(local_doc)

            web_summary = ""
            if include_web_fallback and (not local_summary or needs_web_fallback):
                web_summary = self._fetch_official_reference(uri, local_doc=local_doc)

            combined = "\n\n".join(part for part in (local_summary, web_summary) if part)
            if combined:
                result_parts.append(combined)

        return "\n\n---\n\n".join(result_parts)

    def get_rules(self) -> str:
        """Return the cached content of _rules.md (always injected into system prompt)."""
        if self._rules_cache is None:
            rules_path = os.path.join(self.docs_dir, '_rules.md')
            if os.path.exists(rules_path):
                with open(rules_path, 'r', encoding='utf-8') as f:
                    self._rules_cache = f.read()
            else:
                self._rules_cache = ""
        return self._rules_cache

    def get_function_index_text(self) -> str:
        """
        Return a compact function index string for LLM context.
        Format: "uri | description" per line.
        """
        lines = []
        for entry in self._index:
            lines.append(f"- `{entry['uri']}`: {entry['description']}")
        return "\n".join(lines)

    # ========== Embedding-based Retrieval ==========

    def _compute_files_hash(self) -> str:
        """Compute a hash of all md files to detect changes."""
        hasher = hashlib.md5()
        for entry in sorted(self._index, key=lambda x: x['uri']):
            path = self._get_doc_path(entry['uri'])
            if not path or not os.path.exists(path):
                continue
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    hasher.update(chunk)
        return hasher.hexdigest()

    def _estimate_runtime_embedding_bytes(self, cache_size: int | None = None) -> int:
        if cache_size is not None:
            return cache_size * 2

        dims = self._embedding_dimension_hint()
        vector_count = len(self._index)
        if dims <= 0 or vector_count <= 0:
            return 0
        return vector_count * dims * 32

    def _embedding_dimension_hint(self) -> int:
        model = (self.embedding_model or "").lower()
        if "large" in model:
            return 3072
        if "small" in model:
            return 1536
        if "ada" in model:
            return 1536
        return 1536

    def _allow_embedding_initialization(self, cache_size: int | None = None) -> bool:
        estimated_bytes = self._estimate_runtime_embedding_bytes(cache_size=cache_size)
        if estimated_bytes > self.max_runtime_embedding_bytes:
            print(
                "[WaapiDocRetriever] Embedding init skipped due to estimated runtime memory "
                f"pressure ({estimated_bytes} bytes)"
            )
            return False
        return True

    def _load_cached_embeddings(self) -> bool:
        """Try to load embeddings from cache file. Returns True if successful."""
        cache_path = os.path.join(self.docs_dir, '_embeddings.json')
        if not os.path.exists(cache_path):
            return False

        try:
            cache_size = os.path.getsize(cache_path)
            if cache_size > self.max_cache_bytes:
                print(f"[WaapiDocRetriever] Embeddings cache too large ({cache_size} bytes), skipping cache load")
                return False
            if not self._allow_embedding_initialization(cache_size=cache_size):
                return False

            with open(cache_path, 'r', encoding='utf-8') as f:
                cache = json.load(f)

            # Validate hash
            if cache.get('files_hash') != self._compute_files_hash():
                print("[WaapiDocRetriever] Embeddings cache is stale, rebuilding...")
                return False

            cache_scope = cache.get('scope') or {}
            if cache_scope.get('model') != self.embedding_model:
                print("[WaapiDocRetriever] Embeddings cache model mismatch, rebuilding...")
                return False
            if self._normalize_base_url(cache_scope.get('base_url')) != self._normalize_base_url(self.base_url):
                print("[WaapiDocRetriever] Embeddings cache base_url mismatch, rebuilding...")
                return False

            embeddings = cache.get('embeddings', {})
            if not isinstance(embeddings, dict):
                return False

            self._embeddings = embeddings
            if len(self._embeddings) == len(self._index):
                self._embeddings_ready = True
                return True
        except MemoryError:
            self._disable_embeddings("MemoryError while loading embeddings cache, falling back to TF-IDF")
            return False
        except Exception as e:
            print(f"[WaapiDocRetriever] Failed to load embeddings cache: {e}")

        return False

    def _save_embeddings_cache(self):
        """Save embeddings to cache file."""
        cache_path = os.path.join(self.docs_dir, '_embeddings.json')
        cache = {
            'files_hash': self._compute_files_hash(),
            'model': self.embedding_model,
            'scope': self._cache_scope(),
            'embeddings': self._embeddings
        }
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f)
        except MemoryError:
            print("[WaapiDocRetriever] MemoryError while saving embeddings cache, skipped")
        except Exception as e:
            print(f"[WaapiDocRetriever] Failed to save embeddings cache: {e}")

    def build_embeddings(self) -> bool:
        """
        Build embeddings for all function documents using OpenAI Embeddings API.
        Returns True if successful, False if fallback needed.
        """
        # Try loading from cache first
        if self._load_cached_embeddings():
            print(f"[WaapiDocRetriever] Loaded {len(self._embeddings)} cached embeddings")
            return True

        if not self.api_key:
            print("[WaapiDocRetriever] No API key, falling back to TF-IDF")
            return False

        if not self._allow_embedding_initialization():
            return False

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)

            # Prepare texts: uri + description + first few lines of content
            texts = []
            uris = []
            for entry in self._index:
                uri = entry['uri']
                # Use uri + description + abbreviated content for embedding
                embed_text = f"{uri}\n{entry['description']}\n{self._get_doc_excerpt(uri, 500)}"
                texts.append(embed_text)
                uris.append(uri)

            # Batch embed (API supports up to 2048 inputs)
            batch_size = 100
            all_embeddings = {}

            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                batch_uris = uris[i:i + batch_size]

                response = client.embeddings.create(
                    model=self.embedding_model,
                    input=batch_texts
                )

                if len(response.data) != len(batch_texts):
                    print(f"[WaapiDocRetriever] Warning: expected {len(batch_texts)} embeddings, got {len(response.data)}")

                for j, item in enumerate(response.data):
                    if j < len(batch_uris):
                        all_embeddings[batch_uris[j]] = item.embedding

            self._embeddings = all_embeddings
            self._embeddings_ready = True

            # Save cache
            self._save_embeddings_cache()
            print(f"[WaapiDocRetriever] Built and cached {len(self._embeddings)} embeddings")
            return True

        except MemoryError:
            self._disable_embeddings("MemoryError while building embeddings, falling back to TF-IDF")
            return False
        except Exception as e:
            print(f"[WaapiDocRetriever] Embeddings API failed: {e}, falling back to TF-IDF")
            return False

    def _embed_query(self, query: str) -> list:
        """Get embedding vector for a query string."""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)

            response = client.embeddings.create(
                model=self.embedding_model,
                input=[query]
            )
            if not response.data:
                print("[WaapiDocRetriever] Query embedding returned empty data")
                return None
            return response.data[0].embedding
        except MemoryError:
            self._disable_embeddings("MemoryError while embedding query, falling back to TF-IDF")
            return None
        except Exception as e:
            print(f"[WaapiDocRetriever] Query embedding failed: {e}")
            return None

    @staticmethod
    def _cosine_similarity(vec_a, vec_b):
        """Compute cosine similarity between two vectors."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ========== TF-IDF Fallback ==========

    @staticmethod
    def _tokenize(text: str) -> list:
        """Simple tokenizer: lowercase, split on non-alphanumeric, filter short tokens.
        Chinese text is split into character bigrams for better matching."""
        raw = re.findall(r'[a-z0-9\u4e00-\u9fff]+', text.lower())
        tokens = []
        for seg in raw:
            if re.match(r'[\u4e00-\u9fff]', seg):
                # Chinese: emit each character AND overlapping bigrams
                for ch in seg:
                    tokens.append(ch)
                for i in range(len(seg) - 1):
                    tokens.append(seg[i:i+2])
            elif len(seg) > 1:
                tokens.append(seg)
        return tokens

    def _build_tfidf(self):
        """Build TF-IDF index from all documents."""
        if self._tfidf_ready:
            return

        doc_count = len(self._index)
        if doc_count == 0:
            self._tfidf_ready = True
            return

        # Count document frequency for each token
        df = Counter()
        doc_tokens = {}

        for entry in self._index:
            uri = entry['uri']
            # Include URI itself as tokens (split on dots)
            text = f"{uri.replace('.', ' ')} {entry['description']} {self._read_doc_content(uri)}"
            tokens = self._tokenize(text)
            doc_tokens[uri] = tokens
            unique_tokens = set(tokens)
            for token in unique_tokens:
                df[token] += 1

        # Compute IDF
        self._idf = {}
        for token, freq in df.items():
            self._idf[token] = math.log(doc_count / (1 + freq))

        # Compute TF-IDF vectors for each document
        self._doc_tfidf = {}
        for uri, tokens in doc_tokens.items():
            tf = Counter(tokens)
            total = len(tokens) if tokens else 1
            tfidf_vec = {}
            for token, count in tf.items():
                tfidf_vec[token] = (count / total) * self._idf.get(token, 0)
            self._doc_tfidf[uri] = tfidf_vec

        self._tfidf_ready = True

    def _tfidf_score(self, query: str, uri: str) -> float:
        """Compute TF-IDF similarity between query and a document."""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return 0.0

        # Query TF-IDF
        tf = Counter(query_tokens)
        total = len(query_tokens)
        query_vec = {}
        for token, count in tf.items():
            query_vec[token] = (count / total) * self._idf.get(token, 0)

        # Cosine similarity between query and doc vectors
        doc_vec = self._doc_tfidf.get(uri, {})

        # Get all tokens
        all_tokens = set(list(query_vec.keys()) + list(doc_vec.keys()))

        dot = sum(query_vec.get(t, 0) * doc_vec.get(t, 0) for t in all_tokens)
        norm_q = math.sqrt(sum(v * v for v in query_vec.values()))
        norm_d = math.sqrt(sum(v * v for v in doc_vec.values()))

        if norm_q == 0 or norm_d == 0:
            return 0.0
        return dot / (norm_q * norm_d)

    # ========== URI matching boost ==========

    @staticmethod
    def _uri_match_score(query: str, uri: str) -> float:
        """Bonus score if query contains parts of the function URI."""
        query_lower = query.lower()
        uri_lower = uri.lower()

        # Direct URI mention
        if uri_lower in query_lower:
            return 1.0

        # Check URI parts (e.g., "object.create" matches "ak.wwise.core.object.create")
        parts = uri_lower.split('.')
        score = 0.0
        for part in parts:
            if len(part) > 2 and part in query_lower:
                score += 0.3

        return min(score, 0.9)

    # ========== Main Retrieval Method ==========

    @staticmethod
    def _truncate_text(text: str, max_len: int = 120) -> str:
        text = (text or "").strip().replace("\n", " ")
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def get_last_retrieval_meta(self) -> dict:
        """Return metadata for the latest retrieval call."""
        return dict(self._last_retrieval_meta)

    def retrieve(self, query: str, top_k: int = 8) -> str:
        """
        Retrieve the most relevant WAAPI function docs for a given query.
        
        Args:
            query: User's natural language query or instruction.
            top_k: Number of top functions to return.
            
        Returns:
            Concatenated markdown content of the top-K most relevant functions.
        """
        if not self._index:
            self._last_retrieval_meta = {
                "query": query,
                "retrieval_mode": "none",
                "top_k": top_k,
                "top_matches": [],
                "returned_docs": 0,
            }
            return ""

        scores = {}
        retrieval_mode = "tfidf"

        if self._embeddings_ready:
            # Use embedding-based retrieval
            query_vec = self._embed_query(query)
            if query_vec:
                retrieval_mode = "embedding"
                for uri, doc_vec in self._embeddings.items():
                    sim = self._cosine_similarity(query_vec, doc_vec)
                    # Add URI match bonus
                    sim += self._uri_match_score(query, uri) * 0.3
                    scores[uri] = sim
            else:
                # Embedding query failed, fallback to TF-IDF for this query
                retrieval_mode = "tfidf_fallback_query"
                self._build_tfidf()
                for entry in self._index:
                    uri = entry['uri']
                    score = self._tfidf_score(query, uri)
                    score += self._uri_match_score(query, uri) * 0.5
                    scores[uri] = score
        else:
            # Use TF-IDF fallback
            self._build_tfidf()
            for entry in self._index:
                uri = entry['uri']
                score = self._tfidf_score(query, uri)
                score += self._uri_match_score(query, uri) * 0.5
                scores[uri] = score

        # Sort by score descending, take top_k
        sorted_uris = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        # --- Smart pinned-URI strategy ---
        # If the top scored results are strong matches (score > threshold),
        # give them priority.  Pinned URIs only fill remaining slots.
        pinned_set = set(self.PINNED_URIS)
        selected_uris = []
        seen = set()

        STRONG_MATCH_THRESHOLD = 0.35
        top_score = sorted_uris[0][1] if sorted_uris else 0.0
        has_strong_matches = top_score >= STRONG_MATCH_THRESHOLD

        if has_strong_matches:
            # Strong query matches first — limit pinned to at most 3
            max_pinned = 3
            for uri, score in sorted_uris:
                if len(selected_uris) >= top_k:
                    break
                selected_uris.append((uri, score))
                seen.add(uri)
            # Fill any remaining slots with essential pinned docs
            pinned_added = 0
            for uri in self.PINNED_URIS:
                if uri not in seen and uri in self._doc_paths and pinned_added < max_pinned:
                    if len(selected_uris) < top_k:
                        selected_uris.append((uri, scores.get(uri, 0.0)))
                        seen.add(uri)
                        pinned_added += 1
        else:
            # Weak query — pinned docs first as safety net
            for uri in self.PINNED_URIS:
                if uri in self._doc_paths:
                    selected_uris.append((uri, scores.get(uri, 0.0)))
                    seen.add(uri)
            remaining_slots = max(0, top_k - len(selected_uris))
            for uri, score in sorted_uris:
                if uri not in seen and remaining_slots > 0:
                    selected_uris.append((uri, score))
                    seen.add(uri)
                    remaining_slots -= 1

        # Concatenate docs
        result_parts = []
        for uri, score in selected_uris:
            content = self._read_doc_content(uri)
            if content:
                result_parts.append(content)

        top_matches = [{"uri": uri, "score": round(float(score), 6)} for uri, score in selected_uris]
        self._last_retrieval_meta = {
            "query": query,
            "retrieval_mode": retrieval_mode,
            "top_k": top_k,
            "top_matches": top_matches,
            "returned_docs": len(result_parts),
            "pinned": [u for u in self.PINNED_URIS if u in seen],
        }
        top_summary = ", ".join([f"{m['uri']}({m['score']:.4f})" for m in top_matches[:5]]) or "none"
        print(
            f"[WaapiDocRetriever] Retrieval mode={retrieval_mode}, "
            f"query='{self._truncate_text(query)}', returned_docs={len(result_parts)}, top_hits={top_summary}"
        )

        return "\n\n---\n\n".join(result_parts)

    def retrieve_by_uris(self, uris: list) -> str:
        """
        Retrieve docs for specific function URIs (exact match).
        Useful when LLM explicitly requests certain functions.
        
        Args:
            uris: List of function URI strings.
            
        Returns:
            Concatenated markdown content of the requested functions.
        """
        result_parts = []
        for uri in uris:
            content = self._read_doc_content(uri)
            if content:
                result_parts.append(content)
        return "\n\n---\n\n".join(result_parts)

    # ========== On-demand doc tools (exposed to LLM execution env) ==========

    def lookup_doc(self, query_or_uri: str, top_k: int = 3) -> str:
        """Look up WAAPI documentation by URI or natural language query.

        If *query_or_uri* contains ``ak.`` it is treated as a URI pattern and
        matched against the index (exact first, then substring).  Otherwise a
        semantic retrieve is performed.

        Returns human-readable documentation text.
        """
        q = (query_or_uri or "").strip()
        if not q:
            return "Please provide a WAAPI URI or search keyword."

        # --- URI pattern match ---
        if "ak." in q:
            q_lower = q.lower()
            # Exact match
            for entry in self._index:
                if entry["uri"].lower() == q_lower:
                    content = self._read_doc_content(entry["uri"])
                    if content:
                        return content
            # Substring / prefix match
            matches = [e for e in self._index if q_lower in e["uri"].lower()]
            if matches:
                parts = []
                for e in matches[:top_k]:
                    c = self._read_doc_content(e["uri"])
                    if c:
                        parts.append(c)
                if parts:
                    return "\n\n---\n\n".join(parts)
            # Nothing found by URI – fall through to semantic search

        # --- Semantic / keyword search ---
        return self.retrieve(q, top_k=top_k)

    def search_functions(self, keyword: str, limit: int = 20) -> str:
        """Search the function index by keyword. Returns a compact list of
        matching URIs with descriptions — much lighter than full doc retrieval.

        The LLM can use this to *browse* available APIs before committing to
        a specific function.
        """
        kw = (keyword or "").strip().lower()
        if not kw:
            return "Please provide a search keyword."

        results = []
        for entry in self._index:
            text = f"{entry['uri']} {entry.get('description', '')}".lower()
            if kw in text:
                results.append(f"- `{entry['uri']}`: {entry.get('description', '')[:120]}")

        if not results:
            return f"No WAAPI functions found matching '{keyword}'."
        if len(results) > limit:
            results = results[:limit]
            results.append(f"... and more. Refine your keyword for specific results.")
        return "\n".join(results)

    def extract_uris_from_code(self, code: str) -> list[str]:
        """Extract WAAPI URIs mentioned in a code snippet."""
        pattern = r"""['"]?(ak\.[a-zA-Z0-9_.]+)['"]?"""
        found = set(re.findall(pattern, code))
        # Only keep URIs that exist in the index
        known = {e["uri"] for e in self._index}
        return sorted(found & known)

    def initialize(self) -> str:
        """
        Full initialization: load index, build/load embeddings.
        Returns status message.
        """
        if not self._index:
            return "No WAAPI docs found"

        signature = self._current_init_signature()
        if signature == self._last_init_signature and self._last_init_status:
            return self._last_init_status

        try:
            success = self.build_embeddings()
            if success:
                status = f"Embeddings ready ({len(self._embeddings)} functions)"
            else:
                self._build_tfidf()
                status = f"TF-IDF fallback ready ({len(self._doc_tfidf)} functions)"
        except MemoryError:
            self._disable_embeddings("MemoryError during initialize(), falling back to TF-IDF")
            self._build_tfidf()
            status = f"TF-IDF fallback ready ({len(self._doc_tfidf)} functions)"

        self._last_init_signature = signature
        self._last_init_status = status
        return status
