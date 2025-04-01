import discord
from discord.ext import commands
from fastapi import FastAPI, HTTPException ,File, UploadFile
import asyncio
import uvicorn
import os
from pdfminer.high_level import extract_text
import docx2txt
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
intents = discord.Intents.default()
intents.message_content = True  # Needed to read message content in most cases

bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()

# Start Discord bot in background
@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    loop.create_task(bot.start(TOKEN))

@app.get("/")
def read_root():
    return {"message": "Discord API is up!"}

@app.post("/send/{channel_id}")
async def send_message(channel_id: int, message: str):
    channel = bot.get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    await channel.send(message)
    return {"status": "Message sent"}

# Optional: a basic command
@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")

@app.post("/parse_resume")
async def parse_resume(file: UploadFile = File(...)):
    # Save the uploaded file temporarily
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as f:
        f.write(await file.read())
    
    # Process the file using resumeparse
    data = extract_resume_data(file_location)
    print("data",data)
    skills = extract_skills(data)
    os.remove(file_location)
    
    return skills

# if __name__ == "__main__":
#     uvicorn.run("main:app", host="0.0.0.0", port=8000)

def extract_resume_data(file_path):
    try:
        ext = os.path.splitext(file_path)[1]
        print("ext",ext)
        print("file_path",file_path)
        if ext == '.pdf':
            text = extract_text(file_path)
        elif ext in ['.docx', '.doc']:
            text = docx2txt.process(file_path)
        else:
            raise ValueError("Unsupported file type")
        return text           

    except Exception as e:
        return {"error": str(e)}
    

def extract_skills(cv_text):
    # Define mapping of sections to possible header keywords
    sections = {
        "skills": ['Skills', 'Technical Skills', 'Technologies', 'Tools', 'Core Competencies'],
        "work_experience": ['Work Experience', 'Professional Experience', 'Experience'],
        "projects": ['Projects', 'Project Experience', 'Key Projects']
    }
    
    # Precompile a regex to detect any section header.
    # This pattern matches a header (case-insensitive), an optional colon or dash, and any text that might be on the same line.
    header_pattern = re.compile(
        r'^\s*(?P<header>' + '|'.join(re.escape(h) for sublist in sections.values() for h in sublist) +
        r')\s*[:\-]?\s*(?P<content>.*)$',
        re.IGNORECASE
    )
    
    # Initialize a dictionary to store lines for each section.
    extracted = {key: [] for key in sections}
    current_section = None
    
    # Process the CV text line by line.
    for line in cv_text.splitlines():
        match = header_pattern.match(line)
        if match:
            # Identify which section the header belongs to.
            header_found = match.group("header").strip()
            for section, keywords in sections.items():
                # Use case-insensitive comparison.
                if header_found.lower() in (k.lower() for k in keywords):
                    current_section = section
                    break
            # If there is additional content on the header line, add it.
            content = match.group("content").strip()
            if current_section and content:
                extracted[current_section].append(content)
        elif current_section:
            # If no new header is found, append the line to the current section.
            extracted[current_section].append(line)
    
    # Join the lines for each section and clean up extra whitespace.
    for section in extracted:
        extracted[section] = "\n".join(extracted[section]).strip()
    
    return extracted