import os
from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ["MONGO_URL"]
db_name = os.environ["DB_NAME"]

client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

status_checks_collection = db["status_checks"]
fact_checks_collection = db["fact_checks"]