from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')
from youtube_transcript_api import YouTubeTranscriptApi
import wikipediaapi

iki_wiki = wikipediaapi.Wikipedia(
    language='en',
    extract_format=wikipediaapi.ExtractFormat.WIKI,
    user_agent='Factuality/1.0 (https://github.com/your-repo) Fact-checking bot'
)

app = FastAPI(title="Factuality - Real-time Fact Checker")

api_router = APIRouter(prefix="/api")