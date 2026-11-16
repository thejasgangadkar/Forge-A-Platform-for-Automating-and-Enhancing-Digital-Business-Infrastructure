import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
# Load the documented control panel (forge.config.env) with priority.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), "forge.config.env"), override=True)

url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(url, key)

def get_supabase():
    return supabase
