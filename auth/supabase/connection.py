# supabaseConnection.py

import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

def create_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in environment variables.")

    #from IPython import embed
    #embed()
    # Create and return the Supabase client
    supabase_client = create_client(url, key)
    return supabase_client
