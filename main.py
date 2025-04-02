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
from groq import Groq

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
api_key = os.getenv("GROQ_API_KEY") 
intents = discord.Intents.default()
intents.message_content = True  # Needed to read message content in most cases

bot = commands.Bot(command_prefix="!", intents=intents)

app = FastAPI()

client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
)

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

# Set your desired save folder
SAVE_FOLDER = "downloads"


@bot.event
async def on_message(message):
    print(f"Received message: {message}")
    # Prevent the bot from responding to itself
    if message.author == bot.user:
        return

    # Check if message has attachments
    if message.attachments:
        for attachment in message.attachments:
            # Validate file type
            if not is_supported_file(attachment.filename):
                await message.channel.send(f"❌ Unsupported file type: {attachment.filename}")
                continue

            try:
                # Save the attachment
                file_path = await save_attachment(attachment, SAVE_FOLDER)

                # Parse the resume
                skills = await parse_resume(file_path)

                # Construct messages for the AI model
                messages = construct_messages(skills)

                # Call the AI model
                completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=messages,
                    temperature=0.6,
                    max_completion_tokens=500,
                    top_p=0.95
                )
                ai_response = completion.choices[0].message.content
                cleaned_response = ai_response.replace("\n", "")
                print("cleaned_response",cleaned_response)
                # Send the result to the channel
                await message.channel.send(
                    f"📥 File `{attachment.filename}` saved!\n"
                    f"**Skills:** {skills['skills']}\n"
                    f"**Job Titles:** {cleaned_response}\n"
                )
            except Exception as e:
                await message.channel.send(f"❌ Failed to process the file `{attachment.filename}`: {str(e)}")


async def parse_resume(file_location):

    data = extract_resume_data(file_location)
    print("data",data)
    skills = extract_skills(data)
    
    return skills

def is_supported_file(filename):
    supported_extensions = ['.pdf', '.docx', '.doc']
    ext = os.path.splitext(filename)[1].lower()
    return ext in supported_extensions

async def save_attachment(attachment, save_folder):
    file_path = os.path.join(save_folder, attachment.filename)
    os.makedirs(save_folder, exist_ok=True)
    await attachment.save(file_path)
    return file_path

def construct_messages(skills):
    return [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant that analyzes a candidate's skills, work experience, "
                "and projects to suggest roles they are qualified for. "
                "Strictly return a JSON list of job titles without any additional explanation or reasoning also do not repeat job titles and return the top 5 most relevant jobtitles."
            )
        },
        {
            "role": "user",
            "content": f"""
            Skills: {', '.join(skills['skills'])}
            Experience: {', '.join(skills['work_experience'])}
            Projects: {', '.join(skills['projects'])}

            What job titles am I qualified for?
            Please provide a JSON list of job titles only.
            Example: ["Software Engineer", "Data Scientist"]
            """
        }
    ]

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


