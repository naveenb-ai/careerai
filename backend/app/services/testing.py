# test_live.py — put this in your project root temporarily

from app.database import SessionLocal
from app.services.recommendation_engine import RecommendationEngine
import time

db = SessionLocal()

USER_ID = 2  # ← replace with a real user_id from your DB

try:
    engine = RecommendationEngine(db)

    start = time.time()
    results = engine.get_recommendations(USER_ID, limit=10)
    elapsed = time.time() - start

    print(f"✅ Got {len(results)} recommendations in {elapsed:.2f}s")
    print()

    for i, rec in enumerate(results[:3], 1):
        print(f"#{i} {rec.title} @ {rec.company}")
        print(f"   Score: {rec.match_percentage:.1f}% | Label: {rec.match_label}")
        print(f"   Matched: {rec.matched_skills[:3]}")
        print(f"   Missing: {rec.missing_skills[:3]}")
        print()

    # Verify no result has "AI Scored" as label (the old hardcoded value)
    hardcoded = [r for r in results if r.match_label == "AI Scored"]
    assert not hardcoded, f"❌ {len(hardcoded)} results still have hardcoded 'AI Scored' label"
    print("✅ No hardcoded labels — all derived from scores")

    # Verify scores are in range
    for r in results:
        assert 0 <= r.match_percentage <= 100, f"❌ match_percentage out of range: {r.match_percentage}"
    print("✅ All scores in valid range (0–100)")

except Exception as e:
    print(f"❌ Live test failed: {e}")
    import traceback; traceback.print_exc()
finally:
    db.close()

# Add this to test_live.py


# Run twice — second run benefits from any OS-level caching
for run in range(2):
    start = time.time()
    results = engine.get_recommendations(USER_ID, limit=20)
    elapsed = time.time() - start
    print(f"Run {run+1}: {len(results)} results in {elapsed:.2f}s")