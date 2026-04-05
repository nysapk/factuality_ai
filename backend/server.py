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
        transcript = YouTubeTranscriptApi.get_transcript(video_id)

        async with httpx.AsyncClient() as client:
            info = await client.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            )

        meta = info.json() if info.status_code == 200 else {}

        return {
            "title": meta.get("title", "Unknown"),
            "channel": meta.get("author_name", "Unknown"),
            "transcript": transcript
        }

    except (TranscriptsDisabled, NoTranscriptFound):
        raise HTTPException(status_code=404, detail="Transcript not available")


# extracting claims

def chunk_transcript(transcript, chunk_size=400):
    words = []
    for t in transcript:
        words.extend(t["text"].split())

    return [" ".join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]


def extract_claims(transcript):
    claims = []

    for chunk in chunk_transcript(transcript):
        if not openai_client:
            continue

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Extract factual claims as JSON array"},
                {"role": "user", "content": chunk}
            ]
        )

        try:
            parsed = json.loads(response.choices[0].message.content)
            for c in parsed:
                claims.append(Claim(
                    text=c["text"],
                    timestamp=c.get("timestamp", "0:00"),
                    context=c.get("context", ""),
                    factual_status="unverified",
                    confidence_score=0,
                    explanation=""
                ))
        except:
            pass

    return claims


# fact checking claims

async def fact_check_claim(claim: Claim):
    if not openai_client:
        return claim

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Fact check this claim and return JSON"},
            {"role": "user", "content": claim.text}
        ]
    )

    try:
        result = json.loads(response.choices[0].message.content)
        claim.factual_status = result.get("factual_status", "unverified")
        claim.confidence_score = result.get("confidence_score", 0)
        claim.explanation = result.get("explanation", "")
    except:
        pass

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