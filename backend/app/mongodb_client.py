import motor.motor_asyncio

# Connection string with provided credentials
MONGO_URI = "mongodb+srv://vsghanta:@Venkatesh7@cluster0.dvivi.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
# Specify the database name; feel free to change "scraped_data" as needed.
db = client.get_database("scraped_data")

def get_scraped_profiles_collection():
    """
    Returns the MongoDB collection for scraped profiles.
    Each document stores a complete profile with structured fields.
    """
    return db.get_collection("scraped_profiles")

def get_scraped_tweets_collection():
    """
    Returns the MongoDB collection for scraped tweets.
    Each document stores tweet data with key fields such as tweet_id, username, text, metrics, etc.
    """
    return db.get_collection("scraped_tweets")
