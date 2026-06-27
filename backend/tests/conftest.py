"""Pytest fixtures shared by the suite.

The tests run against the artifacts produced by `scripts/build_artifacts.py`.
If artifacts are missing, the smoke test will skip with a helpful message
rather than failing the whole run.
"""

from __future__ import annotations

from pathlib import Path
import sys
import pytest

# Ensure the backend/ root is importable when pytest is invoked from any cwd.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

EXPECTED_ARTIFACTS = (
    "movies.parquet",
    "tfidf_vectorizer.joblib",
    "tfidf_matrix.npz",
    "sbert_embeddings.npy",
    "faiss_index.bin",
    "title_index.json",
)


def _artifacts_dir() -> Path:
    return _BACKEND_ROOT / "app" / "data" / "artifacts"


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    return _artifacts_dir()


@pytest.fixture(scope="session")
def artifacts_present(artifacts_dir: Path) -> bool:
    return all((artifacts_dir / name).exists() for name in EXPECTED_ARTIFACTS)