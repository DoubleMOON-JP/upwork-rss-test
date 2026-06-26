from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import httpx
import json
import time

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# 基本エンドポイント
# ──────────────────────────────────────────────
@app.get("/")
async def root():
    return {"message": "Upwork Job Monitor Test Server v2", "status": "running"}

@app.get("/ping")
async def ping():
    return {
        "status":      "ok",
        "message":     "サーバーへの通信成功！",
        "server_time": datetime.utcnow().isoformat() + "Z",
    }

# ──────────────────────────────────────────────
# 確認A：データ受信テスト（エコーバック）
# ──────────────────────────────────────────────
@app.post("/test/receive")
async def receive_jobs(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(status_code=400,
            content={"status": "error", "message": "JSONパースエラー: " + str(e)})

    jobs      = body.get("jobs", [])
    job_count = len(jobs)

    sample_jobs = []
    for job in jobs[:3]:
        sample_jobs.append({
            "title":   job.get("title", ""),
            "budget":  job.get("budget", ""),
            "posted":  job.get("posted", ""),
            "skills":  job.get("skills", []),
        })

    return {
        "status":      "received",
        "message":     f"{job_count}件の案件データを受信しました",
        "received_at": datetime.utcnow().isoformat() + "Z",
        "job_count":   job_count,
        "sample_jobs": sample_jobs,
        "license_key": body.get("license_key", "（未送信）"),
        "page_url":    body.get("page_url", ""),
    }

# ──────────────────────────────────────────────
# 確認B：Gemini APIでAI評価テスト
# ──────────────────────────────────────────────
@app.post("/test/evaluate")
async def evaluate_jobs(request: Request):
    """
    エクステンションから案件データ＋Gemini APIキーを受け取り、
    AIがスコアリングして結果を返す
    """
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse(status_code=400,
            content={"status": "error", "message": "JSONパースエラー: " + str(e)})

    api_key = body.get("api_key", "")
    jobs    = body.get("jobs", [])
    profile = body.get("profile", {})

    if not api_key:
        return JSONResponse(status_code=400,
            content={"status": "error", "message": "api_keyが未送信です"})

    if not jobs:
        return JSONResponse(status_code=400,
            content={"status": "error", "message": "案件データが未送信です"})

    # プロフィール情報（未設定の場合はデフォルト）
    skills   = profile.get("skills",   "Python, FastAPI, Excel VBA")
    category = profile.get("category", "バックエンド開発, 自動化, Excel開発")
    min_rate = profile.get("min_rate", "$30")

    # 評価する案件（最大5件・テスト用）
    target_jobs = jobs[:5]

    # ── Geminiへのプロンプト作成 ──
    jobs_text = ""
    for i, job in enumerate(target_jobs):
        skills_str = ", ".join(job.get("skills", [])) if job.get("skills") else "不明"
        jobs_text += f"""
【案件{i+1}】
タイトル: {job.get('title', '')}
予算・時給: {job.get('budget', '不明')}
投稿日時: {job.get('posted', '不明')}
スキル: {skills_str}
説明: {job.get('description', '説明なし')[:200]}
---"""

    prompt = f"""あなたはフリーランサーの案件評価アシスタントです。
以下のフリーランサープロフィールに基づいて、各案件を0〜100点でスコアリングしてください。

【フリーランサープロフィール】
スキル: {skills}
得意カテゴリ: {category}
希望最低時給: {min_rate}

【評価対象案件】
{jobs_text}

【出力形式】
以下のJSON形式のみで回答してください。他のテキストは一切含めないでください。
{{
  "results": [
    {{
      "index": 0,
      "score": 85,
      "reason": "スコアの理由を1〜2文で",
      "recommendation": "応募推奨" または "様子見" または "スキップ"
    }}
  ]
}}"""

    # ── Gemini API呼び出し ──
    gemini_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent?key=" + api_key
    )

    gemini_payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.3,
            "maxOutputTokens": 1000,
        }
    }

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                gemini_url,
                json=gemini_payload,
                headers={"Content-Type": "application/json"}
            )

        elapsed = round(time.time() - start_time, 2)

        if res.status_code != 200:
            error_body = res.text[:300]
            return JSONResponse(status_code=502, content={
                "status":     "gemini_error",
                "message":    f"Gemini APIエラー: HTTP {res.status_code}",
                "detail":     error_body,
                "elapsed_sec": elapsed,
            })

        gemini_data = res.json()

        # レスポンスからテキスト抽出
        raw_text = ""
        try:
            raw_text = gemini_data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            return JSONResponse(status_code=502, content={
                "status":  "parse_error",
                "message": "Geminiレスポンスのパースに失敗: " + str(e),
                "raw":     str(gemini_data)[:300],
            })

        # JSONブロックを抽出（正規表現で確実に抽出）
        import re
        clean_text = raw_text.strip()

        # まず { から } までを正規表現で直接抽出（最も確実）
        json_match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if json_match:
            clean_text = json_match.group(0)
        else:
            # フォールバック：```で囲まれた部分を取得
            code_match = re.search(r'```(?:json)?\s*(.*?)\s*```', clean_text, re.DOTALL)
            if code_match:
                clean_text = code_match.group(1)
        clean_text = clean_text.strip()

        # JSONパース
        try:
            ai_result = json.loads(clean_text)
        except json.JSONDecodeError as je:
            return JSONResponse(status_code=502, content={
                "status":        "json_parse_error",
                "message":       "AIレスポンスのJSON変換に失敗",
                "parse_error":   str(je),
                "clean_text":    clean_text[:300],
                "raw_text_repr": repr(raw_text[:200]),
            })

        # 元の案件データとスコアを結合
        scored_jobs = []
        for r in ai_result.get("results", []):
            idx = r.get("index", 0)
            if idx < len(target_jobs):
                job = target_jobs[idx]
                scored_jobs.append({
                    "title":          job.get("title", ""),
                    "url":            job.get("url", ""),
                    "budget":         job.get("budget", ""),
                    "posted":         job.get("posted", ""),
                    "skills":         job.get("skills", []),
                    "score":          r.get("score", 0),
                    "reason":         r.get("reason", ""),
                    "recommendation": r.get("recommendation", ""),
                })

        # スコア降順にソート
        scored_jobs.sort(key=lambda x: x["score"], reverse=True)

        return {
            "status":        "success",
            "message":       f"{len(scored_jobs)}件の案件をAIが評価しました",
            "evaluated_at":  datetime.utcnow().isoformat() + "Z",
            "elapsed_sec":   elapsed,
            "job_count":     len(scored_jobs),
            "scored_jobs":   scored_jobs,
        }

    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={
            "status":  "timeout",
            "message": "Gemini APIがタイムアウトしました（30秒）",
        })
    except httpx.RequestError as e:
        return JSONResponse(status_code=503, content={
            "status":  "connection_error",
            "message": "Gemini APIへの接続エラー: " + str(e),
        })
