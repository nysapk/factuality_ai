import asyncio
from datetime import datetime, timezone
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import wikipediaapi
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

from db import fact_checks_collection, status_checks_collection


# env
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

openai_client = None
api_key = os.environ.get("OPENAI_API_KEY")

if api_key and api_key != "your_openai_api_key_here":
    openai_client = OpenAI(api_key=api_key)


wiki_wiki = wikipediaapi.Wikipedia(
    language="en",
    extract_format=wikipediaapi.ExtractFormat.WIKI,
    user_agent="factuality-ai"
)

app = FastAPI()
api_router = APIRouter(prefix="/api")


# models

class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


class YouTubeRequest(BaseModel):
    url: str


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    timestamp: str
    context: str
    factual_status: str
    confidence_score: float
    explanation: str
    sources: List[str] = []


class FactCheckResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    youtube_url: str
    video_title: str
    channel_name: str
    transcript_length: int
    claims: List[Claim]
    processing_time: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_claims: int
    true_claims: int
    false_claims: int
    partial_claims: int
    unverified_claims: int


# helpers

def clean_mongo_doc(doc):
    if not doc:
        return doc
    doc.pop("_id", None)
    return doc


def clean_mongo_docs(docs):
    return [clean_mongo_doc(doc) for doc in docs]


@app.on_event("startup")
async def startup():
    await fact_checks_collection.create_index("id", unique=True)
    await fact_checks_collection.create_index("created_at")
    await fact_checks_collection.create_index("youtube_url")
    await status_checks_collection.create_index("id", unique=True)


def extract_youtube_video_id(url: str):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


# transcript

async def get_youtube_transcript(video_id: str):
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id).to_raw_data()

        async with httpx.AsyncClient() as client:
            info = await client.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )

        meta = info.json() if info.status_code == 200 else {}

        return {
            "title": meta.get("title", "Unknown"),
            "channel": meta.get("author_name", "Unknown"),
            "transcript": transcript,
        }

    except (TranscriptsDisabled, NoTranscriptFound) as e:
        raise HTTPException(status_code=404, detail=f"Transcript not available: {e}")


# extracting claims

def chunk_transcript(transcript, chunk_size=400):
    words = []
    for t in transcript:
        words.extend(t["text"].split())

    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]


def parse_json_maybe_wrapped(text: str):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    return json.loads(text)


def extract_claims(transcript):
    claims = []

    if not transcript:
        return claims

    if not openai_client:
        # fallback mode if no OpenAI key
        for item in transcript:
            text = item.get("text", "").strip()
            if not text:
                continue

            has_number = any(ch.isdigit() for ch in text)
            long_enough = len(text.split()) >= 8

            if has_number or long_enough:
                start_seconds = int(item.get("start", 0))
                minutes = start_seconds // 60
                seconds = start_seconds % 60

                claims.append(
                    Claim(
                        text=text,
                        timestamp=f"{minutes}:{seconds:02d}",
                        context="Fallback extraction without OpenAI",
                        factual_status="unverified",
                        confidence_score=0.0,
                        explanation="Extracted without OpenAI; not yet fact-checked",
                        sources=[],
                    )
                )

            if len(claims) >= 15:
                break

        return claims

    chunks = chunk_transcript(transcript, chunk_size=350)

    for i, chunk in enumerate(chunks):
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You extract factual claims from transcripts.

                    Return ONLY a valid JSON array.
                    Each item must be an object with:
                    - text
                    - timestamp
                    - context

                    Rules:
                    - Include only specific, checkable factual claims
                    - Do not include opinions, jokes, rhetorical questions, or vague statements
                    - Keep the claim text concise but faithful
                    - Return at most 8 claims

                    Example:
                    [
                    {
                        "text": "Humans spend about one-third of their lives asleep.",
                        "timestamp": "0:15",
                        "context": "Speaker explains how much time humans spend sleeping."
                    }
                    ]"""
                    },
                    {"role": "user", "content": chunk},
                ],
                temperature=0.1,
                max_tokens=1200,
            )

            raw = response.choices[0].message.content or ""
            print(f"\n--- RAW CLAIM OUTPUT chunk {i} ---\n{raw}\n")

            parsed = parse_json_maybe_wrapped(raw)

            if not isinstance(parsed, list):
                print(f"Chunk {i}: parsed output is not a list")
                continue

            for c in parsed:
                text = (c.get("text") or "").strip()
                if not text:
                    continue

                claims.append(
                    Claim(
                        text=text,
                        timestamp=c.get("timestamp", "0:00"),
                        context=c.get("context", ""),
                        factual_status="unverified",
                        confidence_score=0.0,
                        explanation="Pending fact-check",
                        sources=[],
                    )
                )

        except Exception as e:
            print(f"CLAIM EXTRACTION ERROR on chunk {i}: {e}")

    # dedupe
    deduped = []
    seen = set()
    for claim in claims:
        key = claim.text.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(claim)

    return deduped[:20]

async def search_wikipedia(query: str):
    try:
        page = wiki_wiki.page(query)
        sources = []

        if page.exists():
            sources.append(page.fullurl)

            if hasattr(page, "summary") and page.summary:
                sources.append(f"Wikipedia Summary: {page.summary[:200]}...")

        return sources

    except Exception as e:
        print(f"Wikipedia search failed: {e}")
        return []


# fact checking claims

async def fact_check_claim(claim: Claim):
    wikipedia_sources = await search_wikipedia(claim.text)

    if not openai_client:
        claim.factual_status = "unverified"
        claim.confidence_score = 0.1
        claim.explanation = "No valid OpenAI API key configured."
        claim.sources = wikipedia_sources if wikipedia_sources else []
        return claim

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """You are a professional fact-checker.

                    Return ONLY a valid JSON object:
                    {
                    "factual_status": "true|false|partial|unverified",
                    "confidence_score": 0.0,
                    "explanation": "brief explanation"
                    }"""
                },
                {"role": "user", "content": claim.text},
            ],
            temperature=0.1,
            max_tokens=500,
        )

        raw = response.choices[0].message.content or ""
        print(f"\n--- RAW FACT CHECK OUTPUT ---\n{raw}\n")

        result = parse_json_maybe_wrapped(raw)

        claim.factual_status = result.get("factual_status", "unverified")
        claim.confidence_score = float(result.get("confidence_score", 0.0))
        claim.explanation = result.get("explanation", "")
        claim.sources = wikipedia_sources if wikipedia_sources else []
        return claim

    except Exception as e:
        print(f"FACT CHECK ERROR: {e}")
        claim.factual_status = "unverified"
        claim.confidence_score = 0.1
        claim.explanation = f"Fact-check failed: {e}"
        claim.sources = wikipedia_sources if wikipedia_sources else []
        return claim


# routes

@api_router.post("/status")
async def create_status(input: StatusCheckCreate):
    obj = StatusCheck(**input.dict())
    await status_checks_collection.insert_one(obj.model_dump(mode="json"))
    return obj


@api_router.get("/status")
async def get_status():
    docs = await status_checks_collection.find().to_list(100)
    return clean_mongo_docs(docs)


@api_router.post("/fact-check/youtube")
async def fact_check(req: YouTubeRequest):
    start = asyncio.get_event_loop().time()

    video_id = extract_youtube_video_id(req.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid URL")

    data = await get_youtube_transcript(video_id)

    claims = extract_claims(data["transcript"])
    checked = [await fact_check_claim(c) for c in claims]

    result = FactCheckResult(
        youtube_url=req.url,
        video_title=data["title"],
        channel_name=data["channel"],
        transcript_length=len(data["transcript"]),
        claims=checked,
        processing_time=asyncio.get_event_loop().time() - start,
        total_claims=len(checked),
        true_claims=sum(c.factual_status == "true" for c in checked),
        false_claims=sum(c.factual_status == "false" for c in checked),
        partial_claims=sum(c.factual_status == "partial" for c in checked),
        unverified_claims=sum(c.factual_status == "unverified" for c in checked),
    )

    await fact_checks_collection.insert_one(result.model_dump(mode="json"))

    return result


@api_router.get("/fact-check/outrageous-claims")
async def outrageous():
    docs = await fact_checks_collection.find().sort("created_at", -1).to_list(100)

    docs = clean_mongo_docs(docs)

    results = []
    for fc in docs:
        for claim in fc["claims"]:
            if claim["confidence_score"] < 0.3 or claim["factual_status"] == "false":
                results.append({
                    "video_title": fc["video_title"],
                    "claim": claim
                })

    return results


# app

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)