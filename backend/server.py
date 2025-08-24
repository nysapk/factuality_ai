import datetime
import json
import os
import uuid
from fastapi import FastAPI, APIRouter, HTTPException, logger
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from youtube_transcript_api import YouTubeTranscriptApi
import wikipediaapi
from openai import OpenAI

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Initialize APIs
openai_client = None
openai_api_key = os.environ.get('OPENAI_API_KEY')
if openai_api_key and openai_api_key != "your_openai_api_key_here":
    openai_client = OpenAI(api_key=openai_api_key)

wiki_wiki = wikipediaapi.Wikipedia(
    language='en',
    extract_format=wikipediaapi.ExtractFormat.WIKI,
    user_agent='Factuality/1.0 (https://github.com/your-repo) Fact-checking bot'
)

# Create the main app 
app = FastAPI(title="Factuality - Real-time Fact Checker")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Define Models
class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

class YouTubeRequest(BaseModel):
    url: str

class Claim(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    timestamp: str
    context: str
    factual_status: str  # "true", "false", "partial", "unverified"
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    total_claims: int
    true_claims: int
    false_claims: int
    partial_claims: int
    unverified_claims: int

def extract_youtube_video_id(url: str) -> Optional[str]:
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]+)",
        r"youtube\.com/embed/([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def get_youtube_transcript(video_id: str) -> Dict[str, Any]:
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        # Get video metadata using oEmbed
        async with httpx.AsyncClient() as client:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
            resp = await client.get(oembed_url)
            if resp.status_code == 200:
                info = resp.json()
                title = info.get("title", f"Video {video_id}")
                channel = info.get("author_name", "Unknown Channel")
            else:
                title = f"Video {video_id}"
                channel = "Unknown Channel"
        return {"title": title, "channel": channel, "transcript": transcript_list}
    except Exception as e:
        logger.warning(f"Could not fetch transcript: {e}")
        # Return demo transcript if fails
        demo_transcript = [
            {"text": "AI will replace 50% of all jobs by 2030", "start": 15.2},
            {"text": "The moon landing in 1969 was a hoax staged by Hollywood", "start": 45.8},
        ]
        return {"title": "Demo Video", "channel": "Demo Channel", "transcript": demo_transcript}

def extract_claims_from_transcript(transcript: List[Dict]) -> List[Claim]:
    claims = []
    full_text = " ".join([item["text"] for item in transcript])
    if openai_client:
        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Extract up to 10 factual claims from the transcript in JSON format.",
                    },
                    {"role": "user", "content": full_text},
                ],
                temperature=0.3,
                max_tokens=1000,
            )
            content = resp.choices[0].message.content.strip()
            extracted = json.loads(content)
            for c in extracted:
                claim = Claim(
                    text=c.get("text", ""),
                    timestamp=c.get("timestamp", "0:00"),
                    context=c.get("context", ""),
                    factual_status="unverified",
                    confidence_score=0.0,
                    explanation="Pending fact-check",
                )
                claims.append(claim)
        except Exception as e:
            logger.error(f"OpenAI claim extraction failed: {e}")

    # fallback sample claims
    if not claims:
        for statement in transcript:
            claims.append(
                Claim(
                    text=statement["text"],
                    timestamp=str(statement.get("start", 0)),
                    context="",
                    factual_status="unverified",
                    confidence_score=0.0,
                    explanation="Pending fact-check",
                )
            )
    return claims

async def search_wikipedia(query: str) -> List[str]:
    """Search Wikipedia for information related to a claim"""
    try:
        # Search for relevant Wikipedia pages
        page = wiki_wiki.page(query)
        sources = []
        
        if page.exists():
            sources.append(page.fullurl)
            # Add summary if available
            if hasattr(page, 'summary') and page.summary:
                sources.append(f"Wikipedia Summary: {page.summary[:200]}...")
        
        return sources
    except Exception as e:
        logger.error(f"Wikipedia search failed for query '{query}': {str(e)}")
        return []

def extract_claims_from_transcript(transcript: List[Dict]) -> List[Claim]:
    """Extract factual claims from transcript using OpenAI"""
    claims = []
    
    # Combine transcript into text
    full_text = " ".join([item["text"] for item in transcript])
    
    if openai_client:
        try:
            # Use OpenAI to extract claims
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a fact-checking assistant. Extract factual claims from the given transcript that can be verified. 

                        Focus on:
                        - Specific statistics, numbers, or percentages
                        - Historical facts and dates
                        - Scientific claims
                        - Health claims
                        - Current events

                        Return a JSON array of claims with this structure:
                        [
                        {
                            "text": "exact claim text",
                            "timestamp": "estimated timestamp like 0:15", 
                            "context": "brief context around the claim"
                        }
                        ]

                        Limit to maximum 10 claims. Only return the JSON array, no other text."""
                    },
                    {
                        "role": "user",
                        "content": f"Extract verifiable factual claims from this transcript:\n\n{full_text}"
                    }
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            claims_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                extracted_claims = json.loads(claims_text)
                
                for claim_data in extracted_claims:
                    if isinstance(claim_data, dict):
                        claim = Claim(
                            text=claim_data.get("text", ""),
                            timestamp=claim_data.get("timestamp", "0:00"),
                            context=claim_data.get("context", ""),
                            factual_status="unverified",
                            confidence_score=0.0,
                            explanation="Pending fact-check",
                            sources=[]
                        )
                        claims.append(claim)
                        
            except json.JSONDecodeError:
                logger.error("Failed to parse OpenAI response as JSON")
                
        except Exception as e:
            logger.error(f"OpenAI claim extraction failed: {str(e)}")
    
    # Fallback to sample claims if OpenAI is not available or fails
    if not claims:
        logger.info("Using sample claims for demonstration")
        factual_statements = [
            {"text": "AI will replace 50% of all jobs by 2030", "timestamp": "0:15", "context": "Discussion about AI impact"},
            {"text": "The moon landing in 1969 was a hoax staged by Hollywood", "timestamp": "0:45", "context": "Conspiracy theory discussion"},
            {"text": "Drinking 8 glasses of water daily is essential for health", "timestamp": "1:18", "context": "Health advice segment"},
            {"text": "Vaccines contain microchips for government surveillance", "timestamp": "1:52", "context": "Vaccine discussion"},
            {"text": "Climate change is caused entirely by solar radiation", "timestamp": "2:36", "context": "Climate discussion"}
        ]
        
        for statement in factual_statements:
            claim = Claim(
                text=statement["text"],
                timestamp=statement["timestamp"],
                context=statement["context"],
                factual_status="unverified",
                confidence_score=0.0,
                explanation="Pending fact-check",
                sources=[]
            )
            claims.append(claim)
    
    return claims

async def search_wikipedia(query: str) -> List[str]:
    """Search Wikipedia for information related to a claim"""
    try:
        # Search for relevant Wikipedia pages
        page = wiki_wiki.page(query)
        sources = []
        
        if page.exists():
            sources.append(page.fullurl)
            # Add summary if available
            if hasattr(page, 'summary') and page.summary:
                sources.append(f"Wikipedia Summary: {page.summary[:200]}...")
        
        return sources
    except Exception as e:
        logger.error(f"Wikipedia search failed for query '{query}': {str(e)}")
        return []

async def fact_check_claim(claim: Claim) -> Claim:
    """Fact-check a claim against Wikipedia and using OpenAI"""
    
    # Search Wikipedia for relevant information
    wikipedia_sources = await search_wikipedia(claim.text)
    
    if openai_client:
        try:
            # Prepare context from Wikipedia if available
            wikipedia_context = ""
            if wikipedia_sources:
                wikipedia_context = f"\n\nRelevant Wikipedia information:\n{'; '.join(wikipedia_sources)}"
            
            # Use OpenAI to fact-check the claim
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": """You are a professional fact-checker. Analyze the given claim and provide a factual assessment.

                            Categorize claims as:
                            - "true": Factually accurate and well-supported
                            - "false": Factually incorrect or debunked
                            - "partial": Contains some truth but is misleading or oversimplified
                            - "unverified": Cannot be reliably verified with current information

                            Provide:
                            1. A clear factual_status (true/false/partial/unverified)
                            2. A confidence_score between 0.0-1.0
                            3. A clear explanation of your reasoning
                            4. Relevant sources when possible

                            Return ONLY a JSON object in this format:
                            {
                            "factual_status": "true|false|partial|unverified",
                            "confidence_score": 0.85,
                            "explanation": "Clear explanation of the fact-check result"
                            }"""
                    },
                    {
                        "role": "user",
                        "content": f"Fact-check this claim: '{claim.text}'{wikipedia_context}"
                    }
                ],
                temperature=0.2,
                max_tokens=500
            )
            
            fact_check_text = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                fact_check_result = json.loads(fact_check_text)
                
                claim.factual_status = fact_check_result.get("factual_status", "unverified")
                claim.confidence_score = float(fact_check_result.get("confidence_score", 0.5))
                claim.explanation = fact_check_result.get("explanation", "Fact-check completed")
                
                # Add Wikipedia sources if found
                if wikipedia_sources:
                    claim.sources.extend(wikipedia_sources)
                
                return claim
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse OpenAI fact-check response: {str(e)}")
                
        except Exception as e:
            logger.error(f"OpenAI fact-checking failed: {str(e)}")
    
    # Fallback to predefined fact-check results if OpenAI is not available
    logger.info("Using fallback fact-checking for demonstration")
    
    fact_check_results = {
        "AI will replace 50% of all jobs by 2030": {
            "status": "partial",
            "confidence": 0.6,
            "explanation": "While AI will impact many jobs, the 50% figure lacks consensus. Studies range from 9% to 47% depending on methodology and timeframe.",
        },
        "The moon landing in 1969 was a hoax staged by Hollywood": {
            "status": "false", 
            "confidence": 0.95,
            "explanation": "The Apollo 11 moon landing is well-documented with extensive evidence including retroreflectors, moon rocks, and independent verification from multiple countries including rivals.",
        },
        "Drinking 8 glasses of water daily is essential for health": {
            "status": "partial",
            "confidence": 0.4,
            "explanation": "The '8 glasses a day' rule is not scientifically established. Water needs vary by individual, activity, climate, and overall health.",
        },
        "Vaccines contain microchips for government surveillance": {
            "status": "false",
            "confidence": 0.98, 
            "explanation": "This is a debunked conspiracy theory. Vaccines contain biological components and adjuvants, but no electronic devices. Microchips would be visible in medical imaging.",
        },
        "Climate change is caused entirely by solar radiation": {
            "status": "false",
            "confidence": 0.92,
            "explanation": "While solar variations affect climate, scientific consensus attributes current climate change primarily to human greenhouse gas emissions, not solar activity.",
        }
    }
    
    result = fact_check_results.get(claim.text, {
        "status": "unverified",
        "confidence": 0.1,
        "explanation": "Unable to verify this claim with available sources.",
    })
    
    claim.factual_status = result["status"]
    claim.confidence_score = result["confidence"] 
    claim.explanation = result["explanation"]
    
    # Add Wikipedia sources if found
    if wikipedia_sources:
        claim.sources.extend(wikipedia_sources)
    else:
        claim.sources = ["Wikipedia search yielded no relevant results"]
    
    return claim