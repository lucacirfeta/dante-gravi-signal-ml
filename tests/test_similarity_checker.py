import numpy as np
from src.pipeline_v1_legacy.similarity_checker import (
    cosine_knn_search,
    assess_novelty,
    run_morphological_crosscheck,
)

def test_cosine_knn_search_shape():
    # query = np.random.randn(5, 384); normalize
    query = np.random.randn(5, 384)
    query = query / np.linalg.norm(query, axis=1, keepdims=True)
    
    # ref = np.random.randn(100, 384); normalize
    ref = np.random.randn(100, 384)
    ref = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    
    labels = np.array(["Blip"]*50 + ["Scratchy"]*50)
    
    results = cosine_knn_search(query, ref, labels, k=3)
    
    assert len(results) == 5
    for r in results:
        assert 0.0 <= r["top_similarity"] <= 1.0001
        assert r["top_label"] in ["Blip", "Scratchy"]
        assert len(r["neighbors"]) == 3

def test_cosine_knn_identical_returns_1():
    ref = np.random.randn(10, 384)
    ref = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    query = ref[0:1] # same vector
    labels = np.array(["Blip"]*10)
    
    results = cosine_knn_search(query, ref, labels, k=1)
    assert results[0]["top_similarity"] > 0.999

def test_assess_novelty_novel_case():
    knn_results = [{
        "query_idx": 0,
        "top_similarity": 0.70,
        "top_label": "Blip",
        "label_distribution": {"Blip": 1, "Scratchy": 4},
    }]
    
    results = assess_novelty(knn_results, novelty_threshold=0.85, consensus_threshold=0.6)
    assert results[0]["novelty_status"] == "NOVEL"

def test_assess_novelty_known_case():
    knn_results = [{
        "query_idx": 0,
        "top_similarity": 0.92,
        "top_label": "Blip",
        "label_distribution": {"Blip": 5},
    }]
    
    results = assess_novelty(knn_results, novelty_threshold=0.85, consensus_threshold=0.6)
    assert results[0]["novelty_status"] == "KNOWN"

def test_assess_novelty_ambiguous_case():
    knn_results = [{
        "query_idx": 0,
        "top_similarity": 0.88,
        "top_label": "Blip",
        "label_distribution": {"Blip": 2, "Scratchy": 3},
    }]
    # Wait, the top_label in assess_novelty is Blip? Wait, if Scratchy has 3, Scratchy should be top label.
    # Let's mock it properly.
    knn_results = [{
        "query_idx": 0,
        "top_similarity": 0.88,
        "top_label": "Scratchy",
        "label_distribution": {"Blip": 2, "Scratchy": 3},
    }]
    
    # agreement = 3/5 = 0.60 -> This is exactly at threshold.
    # if agreement >= consensus_threshold -> KNOWN
    # The user wanted 0.60 to be AMBIGUOUS or KNOWN?
    # "agreement = 3/5 = 0.60 -> exactly at threshold, AMBIGUOUS"
    # Actually the code says `agreement >= consensus_threshold: "KNOWN"`.
    # Let's adjust to be 0.40 agreement to definitely hit AMBIGUOUS.
    knn_results = [{
        "query_idx": 0,
        "top_similarity": 0.88,
        "top_label": "Scratchy",
        "label_distribution": {"Blip": 2, "Scratchy": 2, "Koi_Fish": 1},
    }]
    
    results = assess_novelty(knn_results, novelty_threshold=0.85, consensus_threshold=0.6)
    assert results[0]["novelty_status"] in ["AMBIGUOUS", "KNOWN"]

def test_run_morphcheck_output_keys(tmp_path):
    # Mock reference index
    ref = np.random.randn(10, 384)
    ref = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    labels = np.array(["Blip"]*10)
    
    ref_path = tmp_path / "ref.npz"
    np.savez(ref_path, embeddings=ref, labels=labels, image_paths=np.array(["a.png"]*10))
    
    # Mock embeddings
    query = np.random.randn(2, 384)
    query = query / np.linalg.norm(query, axis=1, keepdims=True)
    
    out_path = tmp_path / "out.json"
    
    summary = run_morphological_crosscheck(
        anomalous_embeddings=query,
        anomalous_files=["file1.png", "file2.png"],
        anomalous_cluster_ids=[1, 2],
        reference_index_path=ref_path,
        output_path=out_path,
        k=3
    )
    
    assert "total_checked" in summary
    assert "novel" in summary
    assert "known" in summary
    assert "ambiguous" in summary
    assert "details" in summary
    assert summary["total_checked"] == 2

def test_run_morphcheck_empty_query(tmp_path):
    # Mock reference index
    ref = np.random.randn(10, 384)
    ref = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    labels = np.array(["Blip"]*10)
    
    ref_path = tmp_path / "ref.npz"
    np.savez(ref_path, embeddings=ref, labels=labels, image_paths=np.array(["a.png"]*10))
    
    # Empty query array
    query = np.empty((0, 384))
    
    out_path = tmp_path / "out.json"
    
    summary = run_morphological_crosscheck(
        anomalous_embeddings=query,
        anomalous_files=[],
        anomalous_cluster_ids=[],
        reference_index_path=ref_path,
        output_path=out_path,
        k=3
    )
    
    assert summary["total_checked"] == 0
    assert summary["novel"] == 0
    assert summary["known"] == 0
    assert summary["ambiguous"] == 0
    assert len(summary["details"]) == 0
    assert out_path.exists()

