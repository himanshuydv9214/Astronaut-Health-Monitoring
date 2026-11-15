"""Traceable protocol retrieval (retrieval-only "RAG" without generation).

Two retrieval paths:
  * structured: incident category -> protocols tagged with that category
  * free text : TF-IDF cosine similarity over title + triggers + steps

Everything returned is the stored entry, verbatim, with its source and
approval status. No language model is involved, so nothing can be
hallucinated; if nothing relevant is found, ARES says so.
"""

from __future__ import annotations

import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"


class ProtocolKB:
    def __init__(self, path: Path = KB_DIR / "protocols.json"):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.meta = data["_meta"]
        self.protocols = data["protocols"]
        self.by_id = {p["id"]: p for p in self.protocols}
        docs = [" ".join([p["title"], p["triggers"], " ".join(p["categories"]), " ".join(p["assessment_steps"])])
                for p in self.protocols]
        self.vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.mat = self.vec.fit_transform(docs)

    def for_category(self, categories: list[str], level: int) -> list[dict]:
        cats = set(categories)
        # ESC-01 (critical coordination) is attached only at level 3, never via the catch-all category
        hits = [p for p in self.protocols if cats & set(p["categories"]) and p["id"] != "ESC-01"]
        ids = [p["id"] for p in hits]
        if "GEN-01" not in ids:
            hits.insert(0, self.by_id["GEN-01"])
        if level >= 3 and "ESC-01" not in ids:
            hits.append(self.by_id["ESC-01"])
        return hits

    def search(self, query: str, k: int = 3, min_score: float = 0.08) -> list[tuple[dict, float]]:
        sims = cosine_similarity(self.vec.transform([query]), self.mat)[0]
        order = sims.argsort()[::-1][:k]
        return [(self.protocols[i], float(sims[i])) for i in order if sims[i] >= min_score]

    @staticmethod
    def cite(p: dict) -> str:
        s = p["source"]
        url = f" <{s['url']}>" if s.get("url") else ""
        return f"[{p['id']}] {s['title']}{url} - status: {p['approval']}"


def load_inventory(path: Path = KB_DIR / "medical_inventory.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
