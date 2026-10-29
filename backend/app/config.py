import os

from dotenv import load_dotenv

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# How many PART_OF hops a sub-account can inherit access through.
MAX_DEPTH = int(os.getenv("MAX_HIERARCHY_DEPTH", "8"))

# Enables POST /admin/reseed (resets the demo data). Turn off when deployed publicly.
ENABLE_ADMIN = os.getenv("ENABLE_ADMIN", "1") == "1"

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
