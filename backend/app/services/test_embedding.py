from embedding_service import embed_query, cosine_similarity

print("=== TEST: Embedding Service ===")

text1 = "Python developer internship with machine learning"
text2 = "Looking for ML engineer role using Python"
text3 = "Marketing and sales internship"

vec1 = embed_query(text1)
vec2 = embed_query(text2)
vec3 = embed_query(text3)

print(f"Vector length: {len(vec1)}")  # MUST be 384

sim_good = cosine_similarity(vec1, vec2)
sim_bad = cosine_similarity(vec1, vec3)

print(f"\nSimilarity (related): {sim_good}")
print(f"Similarity (unrelated): {sim_bad}")