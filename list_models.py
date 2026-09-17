"""One-off script: lists the models your Groq API key can actually use.
Run this once, note a model ID from the output, then update MODEL in app/llm.py."""
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

models = client.models.list()
for m in models.data:
    print(m.id)