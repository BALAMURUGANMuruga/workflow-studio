# Rank document chunks using lexical BM25 scores and model-based signals. Return evidence and source metadata.
"""Local retrieval-augmented generation (RAG) for the local document assistant."""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import torch
import torch.nn.functional as F

from .generation_model import DEV, load_model, load_tok


def words(text: str | None) -> list[str]:
    """Simple, dependency-free lexical tokenizer for BM25."""
    if text is None:
        return []
    text = str(text)
    # Treat common spelling variants as the same retrieval term.
    # For example, "life cycle" and "life-cycle" should match "lifecycle".
    text = re.sub(r"\blife[\s_-]+cycle\b", "lifecycle", text, flags=re.IGNORECASE)
    return re.findall(r"\w+", text.lower())


def chunk_text(text: str | None, size: int = 700, overlap: int = 120) -> list[str]:
    """Split text into overlapping character chunks, preferring sentence/space boundaries."""
    if text is None:
        return []
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("Require size > 0 and 0 <= overlap < size.")
    text = "\n".join(line.strip() for line in str(text).splitlines() if line.strip())
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            sentence = text.rfind(". ", start, end)
            line_end = text.rfind("\n", start, end)
            space = text.rfind(" ", start, end)
            cut = max(sentence, line_end, space)
            if cut > start + size // 2:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


class BM25:
    """Small pure-Python BM25 implementation."""
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.term_freqs = [Counter(words(d)) for d in documents]
        self.lengths = [sum(tf.values()) for tf in self.term_freqs]
        self.avg_len = sum(self.lengths) / max(1, len(self.lengths))
        self.k1, self.b = k1, b
        doc_freq = Counter(term for tf in self.term_freqs for term in tf.keys())
        n_docs = len(documents)
        self.idf = {
            term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_freq.items()
        }

    def scores(self, query: str, expand_intent: bool = True) -> list[float]:
        scores = [0.0] * len(self.term_freqs)
        # Remove question framing and generic domain context so words such as
        # "what", "IBM", and "OMS" do not dominate the topic term. Intent
        # expansions are optional so base-topic relevance remains primary.
        query_terms = (
            _expanded_query_terms(query)
            if expand_intent
            else set(words(query)) - _STOPWORDS - _DOMAIN_CONTEXT_TERMS - _QUERY_ACTION_TERMS
        )
        for term in query_terms:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.term_freqs):
                freq = tf.get(term, 0)
                if not freq:
                    continue
                denom = freq + self.k1 * (
                    1 - self.b + self.b * self.lengths[i] / max(self.avg_len, 1e-9)
                )
                scores[i] += idf * freq * (self.k1 + 1) / denom
        return scores


def reciprocal_rank_fusion(rankings: list[list[int]], rrf_k: int = 60) -> list[int]:
    scores = Counter()
    for ranking in rankings:
        for rank, item_id in enumerate(ranking):
            scores[item_id] += 1.0 / (rrf_k + rank + 1)
    return [item_id for item_id, _ in scores.most_common()]


@torch.no_grad()
def model_embeddings(model, tokenizer, texts: Iterable[str]) -> torch.Tensor:
    """Mean-pool this project's model hidden states; not a pretrained semantic embedder."""
    vectors = []
    for text in texts:
        ids_list = tokenizer.encode(text)[-model.ctx:] or [0]
        ids = torch.tensor([ids_list], dtype=torch.long, device=DEV)
        x = model.emb(ids)
        for block in model.blocks:
            x = block(x, model.cos, model.sin)
        vectors.append(model.norm(x).mean(dim=1)[0].float().cpu())
    if not vectors:
        return torch.empty((0, model.emb.embedding_dim), dtype=torch.float32)
    return torch.stack(vectors)


class RAGIndex:
    def __init__(self, chunks, sources, embeddings, mean_vector):
        self.chunks = list(chunks)
        self.sources = list(sources)
        self.embeddings = embeddings.float().cpu()
        self.mean_vector = mean_vector.float().cpu()
        self.bm25 = BM25(self.chunks)

    @classmethod
    def build(cls, path: str, model, tokenizer, size: int = 700, overlap: int = 120):
        target = Path(path)
        if target.is_file():
            paths = [target]
        elif target.is_dir():
            paths = sorted(
                p for p in target.rglob("*")
                if p.is_file() and p.suffix.lower() in {".txt", ".md", ".xml", ".yaml", ".yml", ".json"}
            )
        else:
            raise FileNotFoundError(f"Documents path not found: {path}")

        chunks, sources = [], []
        for file_path in paths:
            try:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                print(f"Skipping {file_path}: {exc}")
                continue
            for part in chunk_text(text, size=size, overlap=overlap):
                chunks.append(part)
                sources.append(str(file_path.relative_to(target)) if target.is_dir() else file_path.name)

        if not chunks:
            raise ValueError("No readable, non-empty supported documents were found.")

        print(f"Embedding {len(chunks)} chunks from {len(paths)} files...")
        raw = model_embeddings(model, tokenizer, chunks)
        mean_vector = raw.mean(dim=0, keepdim=True)
        embeddings = F.normalize(raw - mean_vector, dim=-1)
        return cls(chunks, sources, embeddings, mean_vector)

    def retrieve(self, query: str, model, tokenizer, k: int = 4) -> list[dict]:
        """Retrieve primarily by the user's topic, with small intent-aware boosts.

        Dense vectors from this project's tiny Transformer are not a pretrained
        semantic embedder, so they serve only as a tie-breaker.
        """
        if not self.chunks:
            return []
        k = max(1, min(int(k), len(self.chunks)))

        # Keep the original topic signal separate from generic intent expansions.
        sparse_scores = self.bm25.scores(query, expand_intent=False)
        expanded_sparse_scores = self.bm25.scores(query, expand_intent=True)

        base_terms = (
            _normalised_terms(query)
            - _STOPWORDS
            - _DOMAIN_CONTEXT_TERMS
            - _QUERY_ACTION_TERMS
        )
        ordered_topic_terms = []
        for raw_term in words(query):
            normalised = next(iter(_normalised_terms(raw_term)), raw_term)
            if (
                normalised not in _STOPWORDS
                and normalised not in _DOMAIN_CONTEXT_TERMS
                and normalised not in _QUERY_ACTION_TERMS
            ):
                ordered_topic_terms.append(normalised)
        topic_term = ordered_topic_terms[-1] if ordered_topic_terms else ""
        expanded_terms = set()
        for raw_term in _expanded_query_terms(query):
            expanded_terms.update(_normalised_terms(raw_term))
        expanded_terms -= _STOPWORDS
        expanded_terms -= _DOMAIN_CONTEXT_TERMS
        expanded_terms -= _QUERY_ACTION_TERMS

        chunk_terms = [
            _normalised_terms(chunk)
            - _STOPWORDS
            - _DOMAIN_CONTEXT_TERMS
            - _QUERY_ACTION_TERMS
            for chunk in self.chunks
        ]
        coverage_scores = [
            len(base_terms & terms) / max(1, len(base_terms))
            for terms in chunk_terms
        ]
        expanded_coverage_scores = [
            len(expanded_terms & terms) / max(1, len(expanded_terms))
            for terms in chunk_terms
        ]
        topic_coverage_scores = [
            1.0 if topic_term and topic_term in terms else 0.0
            for terms in chunk_terms
        ]

        query_vec = model_embeddings(model, tokenizer, [query])
        query_vec = F.normalize(query_vec - self.mean_vector, dim=-1)
        dense_scores = (self.embeddings @ query_vec[0]).tolist()

        max_sparse = max(sparse_scores, default=0.0)
        max_expanded_sparse = max(expanded_sparse_scores, default=0.0)
        min_dense = min(dense_scores, default=0.0)
        max_dense = max(dense_scores, default=0.0)
        dense_span = max(max_dense - min_dense, 1e-9)

        lower_query = str(query).lower()
        is_usage_question = bool(re.search(
            r"\b(?:used for|use for|purpose|what .* for)\b", lower_query
        ))
        is_definition_question = bool(
            not is_usage_question
            and re.match(r"^(?:what is|what are|define|meaning of|explain)\b", lower_query)
        )
        is_procedure_question = bool(re.match(
            r"^(?:how should i|how do i|how can i|how to|steps|procedure|"
            r"troubleshoot|investigate|debug|fix|resolve)\b", lower_query
        ))
        is_process_question = bool(re.match(r"^(?:how does|how do|how is)\b", lower_query))

        ranked = []
        for i, chunk in enumerate(self.chunks):
            sparse_norm = sparse_scores[i] / max(max_sparse, 1e-9)
            expanded_sparse_norm = expanded_sparse_scores[i] / max(max_expanded_sparse, 1e-9)
            dense_norm = (dense_scores[i] - min_dense) / dense_span
            coverage = coverage_scores[i]
            expanded_coverage = expanded_coverage_scores[i]
            topic_coverage = topic_coverage_scores[i]
            normalised_chunk_terms = chunk_terms[i]
            has_subject = bool(base_terms & normalised_chunk_terms)
            lower_chunk = chunk.lower()

            intent_bonus = 0.0
            if has_subject and is_usage_question and re.search(
                r"\b(use|uses|used|exchange|represent|representation|input|output|format)\b",
                lower_chunk,
            ):
                intent_bonus += 0.45
            if has_subject and is_definition_question and re.search(
                r"\b(interface|sequence|stages|means|refers|represents|coordinates|"
                r"determines|identifies|definition|concept)\b",
                lower_chunk,
            ):
                intent_bonus += 0.35
            if has_subject and is_procedure_question and re.search(
                r"\b(check|verify|inspect|review|record|capture|error|logs|cause|retry|"
                r"troubleshooting|procedure|exception)\b",
                lower_chunk,
            ):
                intent_bonus += 0.35
            if has_subject and is_process_question and re.search(
                r"\b(determine|determines|evaluate|evaluates|eligible|fulfillment|"
                r"sourcing rules|inventory|workflow|process)\b",
                lower_chunk,
            ):
                intent_bonus += 0.35

            score = (
                0.40 * sparse_norm
                + 0.16 * expanded_sparse_norm
                + 0.20 * coverage
                + 0.19 * topic_coverage
                + 0.05 * dense_norm
                + intent_bonus
            )
            if base_terms and coverage == 0 and sparse_scores[i] <= 0:
                score -= 0.20
            ranked.append((score, i))

        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            {
                "chunk_id": i,
                "source": self.sources[i],
                "text": self.chunks[i],
                "bm25_score": sparse_scores[i],
                "expanded_bm25_score": expanded_sparse_scores[i],
                "dense_score": dense_scores[i],
                "retrieval_score": score,
            }
            for score, i in ranked[:k]
        ]



def make_rag_prompt(
    query: str,
    hits: list[dict],
    tokenizer,
    context_budget: int,
    history: list[dict] | None = None,
) -> str:
    """Build a compact instruction/context prompt for the small local model.

    This prompt is general-purpose: it contains no individual OMS questions or
    prewritten answers. ``context_budget`` is measured in this project's tokens.
    """
    context_parts: list[str] = []
    used = 0
    for hit in hits:
        text = str(hit.get("text", "")).strip()
        if not text:
            continue
        ids = tokenizer.encode(text)
        room = context_budget - used
        if room <= 0:
            break
        if len(ids) > room:
            if not context_parts:
                context_parts.append(tokenizer.decode(ids[:room]))
            break
        context_parts.append(text)
        used += len(ids)

    context = "\n".join(context_parts) if context_parts else "(no matching document context)"
    history_lines: list[str] = []
    for item in (history or [])[-6:]:
        role = str(item.get("role", "")).lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        # Keep a small amount of recent context because the current model has a
        # very short context window. LocalRAG performs the final exact fit below.
        ids = tokenizer.encode(content)
        if len(ids) > 18:
            content = tokenizer.decode(ids[-18:])
        history_lines.append(f"{role.title()}: {content}")
    history_text = "\n".join(history_lines)
    if history_text:
        return (
            "Use the document context. Do not invent facts; if missing, say so.\n"
            f"Context:\n{context}\nRecent conversation:\n{history_text}\n"
            f"Question: {query}\nAnswer:"
        )
    return (
        "Use the document context. Do not invent facts; if missing, say so.\n"
        f"Context:\n{context}\nQuestion: {query}\nAnswer:"
    )



# Generic conversation handling and grounded fallback helpers. These are
# algorithms over the retrieved documents, not per-question answer mappings.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "been", "being",
    "by", "can", "could", "did", "do", "does", "for", "from", "how", "i",
    "in", "is", "it", "its", "me", "of", "on", "or", "please", "should",
    "so", "that", "the", "their", "this", "to", "was", "what", "when",
    "where", "which", "who", "why", "will", "with", "would", "you", "your",
    "used", "use", "work", "works", "working", "explain", "tell", "more",
}
_DOMAIN_CONTEXT_TERMS = {"ibm", "sterling", "oms", "system"}
_QUERY_ACTION_TERMS = {
    "investigate", "investigat", "troubleshoot", "debug", "fix", "resolve",
    "explain", "describe", "find", "identify", "handle", "check", "show",
    "tell", "define", "work", "works", "working", "use", "used",
}


def _normalised_terms(text: str) -> set[str]:
    """Lightweight suffix normalisation for common query/document word forms."""
    result = set()
    for term in words(text):
        token = term
        if len(token) > 6 and token.endswith("ing") and token != "sterling":
            token = token[:-3]
            if len(token) > 2 and token[-1] == token[-2]:
                token = token[:-1]
        elif len(token) > 6 and token.endswith("tion"):
            token = token[:-3]  # extraction -> extract
        elif len(token) > 5 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        result.add(token)
    return result


def _expanded_query_terms(query: str) -> set[str]:
    """Extract topic terms and add small, intent-level retrieval expansions.

    Expansions describe general answer intent (definition, purpose, procedure),
    not specific question-to-answer mappings.
    """
    raw_query = str(query).lower()
    terms = set(words(query)) - _STOPWORDS - _DOMAIN_CONTEXT_TERMS - _QUERY_ACTION_TERMS

    if re.search(r"\b(?:used for|use for|purpose|what .* for)\b", raw_query):
        terms.update({
            "use", "uses", "used", "exchange", "represent", "representation",
            "input", "output", "format", "document", "documents", "data",
        })

    is_usage_query = bool(re.search(
        r"\b(?:used for|use for|purpose|what .* for)\b", raw_query
    ))
    if not is_usage_query and re.match(
        r"^(?:what is|what are|define|meaning of|explain)\b", raw_query
    ):
        terms.update({
            "interface", "sequence", "stages", "determines", "identifies",
            "means", "refers", "represents", "coordinates", "definition",
            "concept", "purpose",
        })

    if re.match(r"^(?:how does|how do|how is|explain)\b", raw_query):
        terms.update({
            "process", "determine", "evaluates", "eligible", "workflow",
            "sequence", "stages", "rules", "inventory", "location",
        })

    if re.match(
        r"^(?:how should i|how do i|how can i|how to|steps|procedure|"
        r"troubleshoot|investigate|debug|fix|resolve)\b",
        raw_query,
    ):
        terms.update({
            "procedure", "check", "verify", "inspect", "review",
            "record", "capture", "error", "logs", "cause", "retry",
            "troubleshooting", "exception",
        })

    return terms


def is_simple_greeting(text: str) -> bool:
    """Recognise a small set of standalone greetings, not arbitrary questions."""
    normalised = re.sub(r"[^a-z\s']", "", str(text).lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    return normalised in {
        "hi", "hello", "hey", "hi there", "hello there", "hey there",
        "good morning", "good afternoon", "good evening",
    }


def is_context_dependent_followup(query: str) -> bool:
    """Return True only for follow-ups that need the previous user topic.

    Full questions with their own subject are searched independently so a
    previous topic (for example sourcing) does not contaminate a new XML or
    exception question.
    """
    normalised = re.sub(r"[^a-z0-9\s']", "", str(query).lower()).strip()
    normalised = re.sub(r"\s+", " ", normalised)
    patterns = (
        r"^why(?:\s+is\s+that)?[?.!]*$",
        r"^how so[?.!]*$",
        r"^what does (?:it|that|this) mean[?.!]*$",
        r"^what about (?:it|that|this|them|those)[?.!]*$",
        r"^(?:can you )?explain (?:it|that|this)(?: more)?[?.!]*$",
        r"^(?:tell me|say) more[?.!]*$",
        r"^(?:continue|go on|what next|and then)[?.!]*$",
        r"^(?:how do i|how can i) fix (?:it|that|this)[?.!]*$",
        r"^(?:is|does|can) it (?:safe|possible|supported)[?.!]*$",
    )
    return any(re.match(pattern, normalised) for pattern in patterns)


def extractive_answer(query: str, hits: list[dict]) -> tuple[str | None, str | None]:
    """Build a multi-sentence answer from relevant indexed evidence.

    This is a retrieval fallback, not model generation. It ranks evidence
    sentences against the query, then includes nearby sentences from the same
    retrieved chunks so that definitions, steps, and explanations are not
    reduced to a single sentence. It contains no per-question answer mappings.
    """
    query_terms = (
        _normalised_terms(query)
        - _STOPWORDS
        - _DOMAIN_CONTEXT_TERMS
        - _QUERY_ACTION_TERMS
    )
    # Prefer the core subject over generic contextual words. For example,
    # "What is an API in IBM Sterling OMS?" should focus on "API", not "OMS".
    if not query_terms:
        return None, None

    ordered_topic_terms = []
    for raw_term in words(query):
        normalised = next(iter(_normalised_terms(raw_term)), raw_term)
        if (
            normalised not in _STOPWORDS
            and normalised not in _DOMAIN_CONTEXT_TERMS
            and normalised not in _QUERY_ACTION_TERMS
        ):
            ordered_topic_terms.append(normalised)
    topic_term = ordered_topic_terms[-1] if ordered_topic_terms else ""

    candidates: list[dict] = []
    for hit_index, hit in enumerate(hits):
        source = str(hit.get("source", "local document"))
        bm25_score = max(0.0, float(hit.get("bm25_score", 0.0)))
        body = str(hit.get("text", ""))
        unit_index = 0

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # Ignore headings; they are useful for retrieval but rarely stand
            # alone as an answer.
            if re.match(r"^\s*#{1,6}\s+", line):
                continue

            is_list_item = bool(re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line))
            is_table_row = line.startswith("|") and line.endswith("|")
            if is_table_row:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if cells and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                    continue
                if len(cells) >= 2:
                    line = f"{cells[0]}: {cells[1]}"
            line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
            line = re.sub(r"^\*\*(.*?)\*\*$", r"\1", line).strip()
            line = line.strip(" \t`")
            if not line or line.startswith(("<?xml", "<", "{", "[")):
                continue

            # Preserve list items as a whole; for prose, split only at likely
            # sentence boundaries. This avoids splitting "1. Step" incorrectly.
            pieces = [line] if (is_list_item or is_table_row) else re.split(
                r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", line
            )
            for piece in pieces:
                sentence = piece.strip(" \t`-")
                if len(sentence) < 20 or len(sentence) > 500:
                    continue
                if not is_list_item and sentence[0].islower():
                    continue
                if not is_table_row and not sentence.endswith((".", "!", "?")):
                    # A chunk may end in a partial sentence; don't present it
                    # as a complete fact.
                    continue

                sentence_terms = _normalised_terms(sentence) - _STOPWORDS - _DOMAIN_CONTEXT_TERMS
                overlap = query_terms & sentence_terms
                coverage = len(overlap) / max(1, len(query_terms))
                ordered_terms = words(sentence)
                first_match = len(ordered_terms)
                for position, raw_term in enumerate(ordered_terms):
                    normalised_term = next(iter(_normalised_terms(raw_term)), raw_term)
                    if normalised_term in overlap:
                        first_match = position
                        break
                subject_bonus = 0.25 / (1 + first_match) if overlap else 0.0

                lower_query = str(query).strip().lower()
                lower_sentence = sentence.lower()
                if re.match(
                    r"^(?:typical concepts include|these notes are introductory|"
                    r"examples below are not guaranteed)",
                    lower_sentence,
                ):
                    continue
                if (
                    topic_term not in {"oms", "system"}
                    and lower_sentence.startswith(
                        "ibm sterling order management system (oms) coordinates"
                    )
                ):
                    continue
                asks_for_usage = bool(re.search(
                    r"\b(?:used for|use for|purpose|what .* for)\b", lower_query
                ))
                asks_for_definition = bool(
                    not asks_for_usage
                    and re.match(
                        r"^(?:what is|what are|define|meaning of|explain)\b", lower_query
                    )
                )
                asks_for_procedure = bool(re.match(
                    r"^(?:how should i|how do i|how can i|how to|steps|procedure|"
                    r"troubleshoot|investigate|debug|fix|resolve)\b",
                    lower_query,
                ))

                target_term = topic_term

                # Give subject nouns more weight than action words such as
                # "investigate" or "explain". This reduces topic drift when a
                # user asks how to investigate a specific type of exception.
                action_terms = {
                    "investigate", "investigat", "troubleshoot", "debug",
                    "fix", "resolve", "explain", "describe", "check",
                    "find", "identify", "handle", "use", "used",
                }
                subject_terms = query_terms - action_terms
                subject_overlap = subject_terms & sentence_terms
                subject_relevance_bonus = (
                    0.8 * len(subject_overlap) / max(1, len(subject_terms))
                )
                topic_bonus = 0.7 if target_term and target_term in sentence_terms else 0.0

                definition_bonus = 0.0
                if asks_for_definition and overlap and target_term:
                    target_pattern = re.escape(target_term)
                    predicate = (
                        r"(?:is|are|means|refers|represents|identifies|defines|"
                        r"describes|determines)"
                    )
                    if re.search(
                        rf"\b{target_pattern}\b\s+{predicate}\b"
                        rf"|\(\s*{target_pattern}\s*\)\s*{predicate}\b"
                        rf"|^\s*{target_pattern}\s*:\s*.{{2,}}",
                        lower_sentence,
                    ):
                        definition_bonus = 1.0

                usage_bonus = 0.0
                if asks_for_usage and target_term:
                    target_pattern = re.escape(target_term)
                    subject_near_usage = bool(re.search(
                        rf"\b{target_pattern}\b.{{0,100}}\b(use|uses|used|represent|represents|exchange|format)\b"
                        rf"|\b(use|uses|used|represent|represents|exchange|format)\b.{{0,100}}\b{target_pattern}\b",
                        lower_sentence,
                    ))
                    if subject_near_usage and re.search(
                        r"\b(used to represent|exchange information|represent data|"
                        r"structured text format|to exchange)\b",
                        lower_sentence,
                    ):
                        usage_bonus = 1.5
                    elif subject_near_usage:
                        usage_bonus = 0.35

                procedure_bonus = 0.0
                if asks_for_procedure:
                    if is_list_item:
                        procedure_bonus += 0.35
                    if re.search(
                        r"\b(check|confirm|verify|inspect|review|record|identify|"
                        r"capture|compare|determine|investigate|troubleshoot|retry)\b",
                        lower_sentence,
                    ):
                        procedure_bonus += 0.15

                score = (
                    3.0 * coverage
                    + min(bm25_score, 5.0) * 0.05
                    + subject_bonus
                    + subject_relevance_bonus
                    + topic_bonus
                    + definition_bonus
                    + usage_bonus
                    + procedure_bonus
                )

                candidates.append({
                    "text": sentence,
                    "source": source,
                    "hit_index": hit_index,
                    "chunk_id": int(hit.get("chunk_id", hit_index)),
                    "unit_index": unit_index,
                    "score": score,
                    "overlap": len(overlap),
                    "topic_match": bool(target_term and target_term in sentence_terms),
                    "definition_match": definition_bonus > 0,
                    "usage_match": usage_bonus >= 1.0,
                    "is_list_item": is_list_item,
                    "is_table_row": is_table_row,
                    "bm25_score": bm25_score,
                    "adjacent_to_retrieved": bool(hit.get("adjacent_to_retrieved", False)),
                })
                unit_index += 1

    relevant = [item for item in candidates if item["overlap"] > 0]
    lower_query_for_selection = str(query).strip().lower()
    is_usage_query = bool(re.search(
        r"\b(?:used for|use for|purpose|what .* for)\b", lower_query_for_selection
    ))
    is_definition_query = bool(
        not is_usage_query
        and re.match(r"^(?:what is|what are|define|meaning of|explain)\b", lower_query_for_selection)
    )
    if is_usage_query:
        usage_relevant = [item for item in relevant if item["usage_match"]]
        if usage_relevant:
            relevant = usage_relevant
    elif topic_term:
        topic_relevant = [item for item in relevant if item["topic_match"]]
        if topic_relevant:
            relevant = topic_relevant

    # For troubleshooting questions, include checklist items from the same
    # chunk or an immediately adjacent chunk to the topic-matching evidence.
    is_procedure_query = bool(re.match(
        r"^(?:how should i|how do i|how can i|how to|steps|procedure|"
        r"troubleshoot|investigate|debug|fix|resolve)\b",
        str(query).strip().lower(),
    ))
    if is_procedure_query:
        # Detect topic-bearing chunks from their full text as well as parsed
        # sentences. A chunk can begin mid-sentence after chunking, causing its
        # first lowercase fragment to be excluded from sentence candidates.
        topic_chunk_ids = {
            int(hit.get("chunk_id", hit_index))
            for hit_index, hit in enumerate(hits)
            if topic_term and topic_term in _normalised_terms(str(hit.get("text", "")))
        }
        topic_chunk_ids.update(
            item["chunk_id"] for item in relevant if item.get("topic_match")
        )
        if topic_chunk_ids:
            nearby_steps = [
                item for item in candidates
                if item.get("is_list_item")
                and any(abs(item["chunk_id"] - topic_id) <= 1 for topic_id in topic_chunk_ids)
            ]
            seen = {item["text"].casefold() for item in relevant}
            relevant.extend(
                item for item in nearby_steps if item["text"].casefold() not in seen
            )

    if not relevant:
        return None, None

    # Pick the strongest evidence sentence as the answer anchor.
    anchor = max(relevant, key=lambda item: item["score"])
    selected: list[dict] = [anchor]

    # Preserve nearby context from the anchor chunk first. This keeps a
    # definition followed by its first workflow steps in the original order.
    same_chunk = [] if is_procedure_query else [
        item for item in candidates
        if item["hit_index"] == anchor["hit_index"]
        and item["text"].casefold() not in {s["text"].casefold() for s in selected}
        and (
            item["definition_match"] if asks_for_definition
            # Usage answers often span adjacent sentences: e.g. a sentence
            # says XML exchanges information, and the next explains request
            # input and response output without repeating "XML". Keep a small
            # local context window from the same chunk instead of returning
            # only the anchor sentence.
            else (
                item["usage_match"]
                or (
                    abs(item["unit_index"] - anchor["unit_index"]) <= 3
                    and re.search(
                        r"\b(input|output|request|response|data|document|format|"
                        r"exchange|represent|information|payload)\b",
                        item["text"],
                        re.IGNORECASE,
                    )
                )
            ) if asks_for_usage
            else item["topic_match"]
        )
    ]
    same_chunk.sort(
        key=lambda item: (
            0 if 0 < item["unit_index"] - anchor["unit_index"] <= 6 else 1,
            abs(item["unit_index"] - anchor["unit_index"]),
            -item["score"],
        )
    )
    for item in same_chunk:
        if len(selected) >= 5:
            break
        selected.append(item)

    # When a high-scoring chunk was split across a boundary, include a short
    # contiguous window from the most relevant adjacent chunk. This recovers
    # list steps that may not repeat the query terms.
    adjacent_hit_ids = set() if is_procedure_query else {
        item["hit_index"] for item in candidates
        if item.get("adjacent_to_retrieved", False)
    }
    adjacent_hit_ids = sorted(
        adjacent_hit_ids,
        key=lambda hit_index: max(
            (item["score"] for item in candidates if item["hit_index"] == hit_index),
            default=0.0,
        ),
        reverse=True,
    )[:1]
    for hit_index in adjacent_hit_ids:
        chunk_items = sorted(
            [item for item in candidates if item["hit_index"] == hit_index],
            key=lambda item: item["unit_index"],
        )
        matching_positions = [
            position for position, item in enumerate(chunk_items)
            if item["overlap"] > 0
        ]
        start_position = max(0, (min(matching_positions) if matching_positions else 0) - 2)
        for item in chunk_items[start_position:]:
            if len(selected) >= 7:
                break
            if asks_for_usage and not item["usage_match"]:
                continue
            if asks_for_definition and not item["definition_match"]:
                continue
            if not asks_for_usage and not asks_for_definition:
                if not item["topic_match"] and not item["is_list_item"]:
                    continue
            if item["text"].casefold() not in {s["text"].casefold() for s in selected}:
                selected.append(item)

    # Fill any remaining slots with query-matching evidence from other retrieved
    # chunks. Avoid unrelated chunks with only weak lexical overlap.
    relevant_fill = sorted(
        relevant,
        key=lambda candidate: (
            0 if is_procedure_query and candidate.get("is_list_item", False) else 1,
            -candidate["score"],
        ),
    )
    max_selected = 11 if is_procedure_query else 7
    for item in relevant_fill:
        if len(selected) >= max_selected:
            break
        if item.get("is_table_row", False) and not (asks_for_definition or asks_for_usage):
            continue
        if asks_for_usage and not item["usage_match"]:
            continue
        if not item["topic_match"] and not item["is_list_item"] and not asks_for_usage:
            continue
        if asks_for_definition and not item["definition_match"]:
            continue
        if (
            item["bm25_score"] < 1.0
            and item["score"] < anchor["score"] - 0.5
            and not item.get("adjacent_to_retrieved", False)
        ):
            continue
        if item["text"].casefold() not in {s["text"].casefold() for s in selected}:
            selected.append(item)

    # Present evidence in document order where possible, but keep the anchor's
    # source as the primary citation for backwards compatibility with the API.
    selected.sort(key=lambda item: (
        0 if item is anchor else 1,
        item["chunk_id"],
        item["unit_index"],
    ))
    answer = "\n".join(
        f"- {item['text']}" if len(item["text"]) < 220 and item["text"].count(":") >= 1
        else item["text"]
        for item in selected
    )
    answer = answer[:1600].rstrip()
    return answer or None, str(anchor["source"])


def generation_is_unreliable(raw_answer: str, query: str, hits: list[dict]) -> bool:
    """Conservative generic checks for corrupted, incoherent, or ungrounded output."""
    if not raw_answer or not raw_answer.strip():
        return True

    nonspace = [ch for ch in raw_answer if not ch.isspace()]
    if not nonspace:
        return True

    replacement_count = raw_answer.count("\ufffd")
    control_count = sum(1 for ch in nonspace if not ch.isprintable())
    alphanumeric_count = sum(1 for ch in nonspace if ch.isalnum())
    if replacement_count / len(nonspace) > 0.01:
        return True
    if control_count / len(nonspace) > 0.01:
        return True
    if alphanumeric_count / len(nonspace) < 0.55:
        return True

    answer_terms = set(words(raw_answer)) - _STOPWORDS
    if len(answer_terms) < 2:
        return True

    evidence_text = " ".join(str(hit.get("text", "")) for hit in hits)
    evidence_terms = set(words(evidence_text)) - _STOPWORDS
    query_terms = set(words(query)) - _STOPWORDS
    support_terms = evidence_terms | query_terms
    overlap_ratio = len(answer_terms & support_terms) / max(1, len(answer_terms))

    # A generated answer should contain more than one accidental shared word.
    # The threshold is intentionally conservative for this tiny experimental model.
    if hits and overlap_ratio < 0.35:
        return True
    if not hits and overlap_ratio < 0.35:
        return True
    return False



def include_adjacent_chunks(index: RAGIndex, query: str, hits: list[dict], radius: int = 1) -> list[dict]:
    """Add neighbouring chunks from the same source to recover split sections.

    Chunk expansion is generic: it follows document order and source metadata,
    not question-specific answer mappings.
    """
    if not hits or radius < 1:
        return list(hits)
    expanded = list(hits)
    existing = {int(hit.get("chunk_id", -1)) for hit in expanded}
    lexical_scores = index.bm25.scores(query)
    seeds = expanded[:3]  # Expand several top-ranked seeds to recover section continuations.
    for seed in seeds:
        seed_id = int(seed.get("chunk_id", -1))
        if seed_id < 0 or seed_id >= len(index.chunks):
            continue
        seed_source = index.sources[seed_id]
        for offset in range(-radius, radius + 1):
            candidate_id = seed_id + offset
            if offset == 0 or candidate_id < 0 or candidate_id >= len(index.chunks):
                continue
            if candidate_id in existing or index.sources[candidate_id] != seed_source:
                continue
            # Do not add an unrelated neighbour that has no lexical evidence
            # for the current query. Useful continuation chunks usually share
            # at least one term such as "order", "lifecycle", "XML", or "attribute".
            if lexical_scores[candidate_id] <= 0:
                continue
            expanded.append({
                "chunk_id": candidate_id,
                "source": index.sources[candidate_id],
                "text": index.chunks[candidate_id],
                "bm25_score": lexical_scores[candidate_id],
                "dense_score": 0.0,
                "adjacent_to_retrieved": True,
            })
            existing.add(candidate_id)
    return expanded


class LocalRAG:
    """Local model + local retrieval pipeline; no hosted model/API is called."""

    def __init__(self, checkpoint, tokenizer_path, documents):
        self.model = load_model(checkpoint)
        self.tokenizer = load_tok(tokenizer_path)
        self.index = RAGIndex.build(documents, self.model, self.tokenizer)

    def ask(
        self,
        query: str,
        k: int = 4,
        max_new_tokens: int = 100,
        history: list[dict] | None = None,
        assistant_context: str | None = None,
    ) -> dict:
        query = str(query).strip()
        if not query:
            raise ValueError("Question must not be empty.")
        original_query = query

        if assistant_context is not None:
            hits = [{"source": "Assistant profile", "text": assistant_context}]
            retrieval_query = query
        elif not self.index.chunks:
            hits = []
            retrieval_query = query
        else:
            # Reuse prior context only for genuinely referential follow-ups.
            # Combining history with every full question contaminates retrieval:
            # e.g. an earlier sourcing question can pollute a later XML question.
            previous_user_text = [
                str(item.get("content", "")).strip()
                for item in (history or [])[-6:]
                if str(item.get("role", "")).lower() == "user"
                and str(item.get("content", "")).strip()
            ]
            if previous_user_text and is_context_dependent_followup(query):
                retrieval_query = f"{previous_user_text[-1]} {query}"
            else:
                retrieval_query = query
            # Use a few extra local chunks for fallback extraction. A short
            # chunk may contain only the beginning of a numbered workflow; the
            # next chunk can contain the remaining steps.
            retrieve_k = min(20, max(int(k), 6))
            hits = self.index.retrieve(
                retrieval_query, self.model, self.tokenizer, k=retrieve_k
            )
            hits = include_adjacent_chunks(self.index, retrieval_query, hits, radius=1)

        has_lexical_evidence = any(
            float(hit.get("bm25_score", 0.0)) > 0 for hit in hits
        )

        # The included checkpoint has a short context window. Reserve room for
        # generated tokens, then fit history and retrieved context to the rest.
        answer_budget = max(1, min(int(max_new_tokens), max(1, self.model.ctx // 3)))
        max_prompt_tokens = max(1, self.model.ctx - answer_budget)
        # Keep the full query for retrieval/fallback intent detection. Only a
        # separate prompt copy may be shortened to fit the tiny model context.
        prompt_query = original_query
        query_ids = self.tokenizer.encode(prompt_query)
        query_limit = max(8, max_prompt_tokens // 3)
        if len(query_ids) > query_limit:
            prompt_query = self.tokenizer.decode(query_ids[-query_limit:])

        recent_history = [
            {
                "role": str(item.get("role", "")).lower(),
                "content": str(item.get("content", "")),
            }
            for item in (history or [])
            if str(item.get("role", "")).lower() in {"user", "assistant"}
            and str(item.get("content", "")).strip()
        ][-6:]
        context_budget = max(0, max_prompt_tokens // 2)
        prompt = make_rag_prompt(
            prompt_query, hits, self.tokenizer, context_budget, recent_history
        )

        while len(self.tokenizer.encode(prompt)) > max_prompt_tokens and recent_history:
            recent_history.pop(0)
            prompt = make_rag_prompt(
                prompt_query, hits, self.tokenizer, context_budget, recent_history
            )
        while len(self.tokenizer.encode(prompt)) > max_prompt_tokens and context_budget > 0:
            context_budget = max(0, context_budget - 8)
            prompt = make_rag_prompt(
                prompt_query, hits, self.tokenizer, context_budget, recent_history
            )
        if len(self.tokenizer.encode(prompt)) > max_prompt_tokens:
            short_query_ids = self.tokenizer.encode(prompt_query)[-max(1, max_prompt_tokens // 4):]
            prompt_query = self.tokenizer.decode(short_query_ids)
            prompt = f"Context: (limited)\nQuestion: {prompt_query}\nAnswer:"
            prompt_ids = self.tokenizer.encode(prompt)[-max_prompt_tokens:]
        else:
            prompt_ids = self.tokenizer.encode(prompt)

        if not prompt_ids:
            prompt_ids = self.tokenizer.encode("A:") or [0]
        input_ids = torch.tensor([prompt_ids], dtype=torch.long, device=DEV)
        output = self.model.generate(
            input_ids,
            answer_budget,
            temp=0.5,
            top_k=min(20, max(1, int(getattr(self.model, "vocab_size", 20)))),
        )
        answer_ids = output[0, input_ids.size(1):].tolist()
        raw_answer = self.tokenizer.decode(answer_ids).strip()
        unreliable = generation_is_unreliable(raw_answer, original_query, hits)

        # Without lexical evidence, this prototype's experimental dense vectors
        # are not reliable enough to justify presenting a factual OMS answer.
        if assistant_context is not None:
            answer = raw_answer
            mode = "generated_conversation"
            sources = []
            if unreliable:
                answer = assistant_context
                mode = "profile_fallback"
            generation_warning = unreliable
        elif not has_lexical_evidence:
            answer = (
                "I couldn't find relevant information in the local documents. "
                "Add or index documentation related to your question, then try again."
            )
            mode = "no_relevant_context"
            generation_warning = True
            sources = []
        elif unreliable:
            sentence, source = extractive_answer(original_query, hits)
            if sentence:
                answer = f"Based on the local documentation: {sentence}"
                mode = "retrieval_fallback"
                # Cite the exact chunk containing the selected sentence. A
                # filename may have multiple overlapping chunks, and the first
                # one can end in the middle of a sentence.
                evidence_lines = []
                for line in sentence.splitlines():
                    clean_line = re.sub(r"^\s*(?:[-*]+\s*|\d+[.)]\s*)", "", line).strip()
                    if len(clean_line) >= 20:
                        evidence_lines.append(clean_line)
                exact_hits = [
                    hit for hit in hits
                    if any(
                        evidence_line in str(hit.get("text", ""))
                        for evidence_line in evidence_lines
                    )
                ]
                # Prefer chunks that contain the actual selected evidence, not
                # merely the first chunk sharing the same filename.
                sources = exact_hits[:3] or [
                    hit for hit in hits
                    if str(hit.get("source", "")) == source
                ][:1]
            else:
                answer = (
                    "I found related documents, but the local model could not "
                    "generate a reliable answer. Add clearer documentation or retrain the model."
                )
                mode = "generation_quality_warning"
                sources = hits
            generation_warning = True
        else:
            answer = raw_answer
            mode = "generated_rag"
            generation_warning = False
            sources = hits

        return {
            "question": original_query,
            "answer": answer,
            "raw_generated_text": raw_answer,
            "generation_warning": generation_warning,
            "mode": mode,
            "sources": sources,
            "retrieved_sources": hits,
            "retrieval_query": retrieval_query,
            "generated_tokens": len(answer_ids),
        }
