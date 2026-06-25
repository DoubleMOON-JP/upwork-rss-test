from fastapi import FastAPI
from fastapi.responses import JSONResponse
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime
import time

app = FastAPI()

UPWORK_RSS_BASE = "https://www.upwork.com/ab/feed/jobs/rss"

TEST_KEYWORDS = [
    "python",
    "fastapi",
    "python developer",
]

@app.get("/")
async def root():
    return {"message": "Upwork RSS Test Server", "status": "running"}


@app.get("/test/rss")
async def test_rss():
    """
    UpworkのRSSへのアクセステスト
    複数キーワードでテストし、結果をまとめて返す
    """
    results = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    for keyword in TEST_KEYWORDS:
        url = f"{UPWORK_RSS_BASE}?q={keyword}&sort=recency"
        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)

            elapsed = round(time.time() - start_time, 2)

            if response.status_code == 200:
                try:
                    root_el = ET.fromstring(response.text)
                    items = root_el.findall(".//item")
                    job_count = len(items)

                    sample = None
                    if items:
                        title_el = items[0].find("title")
                        link_el  = items[0].find("link")
                        pub_el   = items[0].find("pubDate")
                        sample = {
                            "title":   title_el.text[:60] if title_el is not None else "N/A",
                            "url":     link_el.text[:80]  if link_el  is not None else "N/A",
                            "pubDate": pub_el.text         if pub_el   is not None else "N/A",
                        }

                    results.append({
                        "keyword":      keyword,
                        "status":       "SUCCESS",
                        "http_code":    response.status_code,
                        "elapsed_sec":  elapsed,
                        "job_count":    job_count,
                        "sample_job":   sample,
                        "content_type": response.headers.get("content-type", ""),
                    })

                except ET.ParseError as e:
                    results.append({
                        "keyword":     keyword,
                        "status":      "XML_PARSE_ERROR",
                        "http_code":   response.status_code,
                        "elapsed_sec": elapsed,
                        "error":       str(e),
                        "raw_preview": response.text[:300],
                    })

            else:
                results.append({
                    "keyword":     keyword,
                    "status":      "HTTP_ERROR",
                    "http_code":   response.status_code,
                    "elapsed_sec": elapsed,
                    "error":       f"HTTP {response.status_code}",
                })

        except httpx.TimeoutException:
            results.append({
                "keyword": keyword,
                "status":  "TIMEOUT",
                "error":   "15秒でタイムアウト",
            })
        except httpx.RequestError as e:
            results.append({
                "keyword": keyword,
                "status":  "CONNECTION_ERROR",
                "error":   str(e),
            })

    success_count = sum(1 for r in results if r["status"] == "SUCCESS")
    summary = {
        "tested_at":     datetime.utcnow().isoformat() + "Z",
        "total_tests":   len(results),
        "success_count": success_count,
        "verdict":       "OK - RSSアクセス可能" if success_count > 0 else "NG - アクセス不可",
        "results":       results,
    }

    return JSONResponse(content=summary)


@app.get("/test/rss/single")
async def test_rss_single(keyword: str = "python"):
    """
    単一キーワードで詳細テスト
    例: /test/rss/single?keyword=python+developer
    """
    url = f"{UPWORK_RSS_BASE}?q={keyword}&sort=recency"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 200:
            root_el = ET.fromstring(response.text)
            items = root_el.findall(".//item")

            jobs = []
            for item in items[:5]:
                title_el = item.find("title")
                link_el  = item.find("link")
                pub_el   = item.find("pubDate")
                desc_el  = item.find("description")

                jobs.append({
                    "title":       title_el.text[:80]        if title_el is not None else "",
                    "url":         link_el.text               if link_el  is not None else "",
                    "pubDate":     pub_el.text                if pub_el   is not None else "",
                    "description": desc_el.text[:200] + "..." if desc_el  is not None and desc_el.text else "",
                })

            return {
                "status":    "SUCCESS",
                "keyword":   keyword,
                "url":       url,
                "http_code": response.status_code,
                "job_count": len(items),
                "jobs":      jobs,
            }
        else:
            return {
                "status":    "HTTP_ERROR",
                "http_code": response.status_code,
                "url":       url,
            }

    except Exception as e:
        return {"status": "ERROR", "error": str(e)}
