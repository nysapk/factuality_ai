import os
from fastapi import FastAPI, APIRouter, HTTPException, logger
from pathlib import Path
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')
from youtube_transcript_api import YouTubeTranscriptApi
import wikipediaapi
from openai import OpenAI

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
