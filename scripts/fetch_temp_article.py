import os
import json
from supabase import create_client

url = "https://xjvmnmfczvwkjiasirsl.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhqdm1ubWZjenZ3a2ppYXNpcnNsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODIwNjgxMywiZXhwIjoyMDkzNzgyODEzfQ.LWI7MaXTdR5Ma1rdvaCtUrDL-C0rNefro5Qj16QIy0o"

supabase = create_client(url, key)

res = supabase.table("posts").select("*").eq("slug", "hojaldritos-salados-variados-receta-facil-para-un-aperitivo-infalible").execute()

with open("temp_article.json", "w", encoding="utf-8") as f:
    json.dump(res.data, f, ensure_ascii=False, indent=2)

print("Article saved to temp_article.json")
