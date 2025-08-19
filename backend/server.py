from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')
from youtube_transcript_api import YouTubeTranscriptApi
import wikipediaapi

