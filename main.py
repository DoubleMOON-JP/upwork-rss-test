from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime
import time

app = FastAPI()

# ── CORS設定（Chromeエクステンションからのアクセスを許可）──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

UPWORK_RSS_BASE = "https://www.upwork.com/ab/feed/jobs/rss"
TEST_KEYWORDS   = ["python", "fastapi", "python developer"]


@app.get("/")
async def root():
    return {"message": "Upwork RSS Test Server", "status": "running"}


# ──────────────────────────────────────────────
# 確認A用：エクステンションからの通信テスト
# ──────────────────────────────────────────────
@app.get("/ping")
async def ping():
    """エクステンションからの到達確認用"""
    return {
        "status":    "ok",
        "message":   "サーバーへの通信成功！",
        "server_time": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/test/receive")
async def receive_jobs(request: Request):
    """
    エクステンションから送られてきたデータを受け取り、
    受信内容をそのまま返す（エコーバック）
    """
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "JSONパースエラー: " + str(e)}
        )

    job_count = len(body.get("jobs", []))
    jobs      = body.get("jobs", [])

    # サンプルとして最初の3件だけ返す
    sample_jobs = []
    for job in jobs[:3]:
        sample_jobs.append({
            "title":       job.get("title", ""),
            "budget":      job.get("budget", ""),
            "posted":      job.get("posted", ""),
            "skills":      job.get("skills", []),
            "url_preview": job.get("url", "")[:60],
        })

    return {
        "status":       "received",
        "message":      f"{job_count}件の案件データを受信しました",
        "received_at":  datetime.utcnow().isoformat() + "Z",
        "job_count":    job_count,
        "sample_jobs":  sample_jobs,
        "license_key":  body.get("license_key", "（未送信）"),
        "page_url":     body.get("page_url", ""),
    }


# ──────────────────────────────────────────────
# 既存のRSSテスト（参考用）
# ──────────────────────────────────────────────
@app.get("/test/rss")
async def test_rss():
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":     "application/rss+xml, application/xml, text/xml, */*",
    }
    for keyword in TEST_KEYWORDS:
        url        = f"{UPWORK_RSS_BASE}?q={keyword}&sort=recency"
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
            elapsed  = round(time.time() - start_time, 2)
            if response.status_code == 200:
                root_el   = ET.fromstring(response.text)
                items     = root_el.findall(".//item")
                job_count = len(items)
                sample    = None
                if items:
                    title_el = items[0].find("title")
                    link_el  = items[0].find("link")
                    pub_el   = items[0].find("pubDate")
                    sample   = {
                        "title":   title_el.text[:60] if title_el is not None else "N/A",
                        "url":     link_el.text[:80]  if link_el  is not None else "N/A",
                        "pubDate": pub_el.text         if pub_el   is not None else "N/A",
                    }
                results.append({
                    "keyword": keyword, "status": "SUCCESS",
                    "http_code": response.status_code,
                    "elapsed_sec": elapsed, "job_count": job_count,
                    "sample_job": sample,
                })
            else:
                results.append({
                    "keyword": keyword, "status": "HTTP_ERROR",
                    "http_code": response.status_code,
                    "elapsed_sec": round(time.time() - start_time, 2),
                    "error": f"HTTP {response.status_code}",
                })
        except httpx.TimeoutException:
            results.append({"keyword": keyword, "status": "TIMEOUT", "error": "15秒でタイムアウト"})
        except httpx.RequestError as e:
            results.append({"keyword": keyword, "status": "CONNECTION_ERROR", "error": str(e)})

    success_count = sum(1 for r in results if r["status"] == "SUCCESS")
    return JSONResponse(content={
        "tested_at":     datetime.utcnow().isoformat() + "Z",
        "total_tests":   len(results),
        "success_count": success_count,
        "verdict":       "OK" if success_count > 0 else "NG",
        "results":       results,
    })
