import sys
sys.stderr = sys.stdout
try:
    from app.scrapers.armenian_news import ALL_NEWS_SCRAPERS
    print("OK - scrapers loaded:", len(ALL_NEWS_SCRAPERS))
except Exception as e:
    import traceback
    traceback.print_exc()

try:
    from app import app
    print("OK - app loaded:", app)
except Exception as e:
    import traceback
    traceback.print_exc()
