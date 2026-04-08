import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from dateutil import parser

# ====== НАСТРОЙКИ ======
CLIENT_ID = "xxx"
CLIENT_SECRET = "xxx"
SECRET_KEY = "xxx"

templates = Jinja2Templates(directory="templates")

# ====== APP ======
app = FastAPI()


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=False,
)

oauth = OAuth()

oauth.register(
    name="google",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile https://www.googleapis.com/auth/calendar.readonly",
        "response_type": "code",
    },
)

# ====== ROUTES ======


@app.get("/info")
async def home(request: Request):
    user = request.session.get("user")
    if user:
        return {"message": "You are logged in", "user": user, "go_to": "/events"}
    return {"message": "Not logged in", "login_url": "/login"}


@app.get("/login")
async def login(request: Request):
    redirect_uri = "http://localhost:8000/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)

    request.session["token"] = token
    request.session["user"] = {"access_token": token["access_token"]}

    return RedirectResponse(url="/")


@app.get("/events")
async def get_events(request: Request):
    token = request.session.get("token")

    if not token:
        return RedirectResponse(url="/login")

    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )

    service = build("calendar", "v3", credentials=creds)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            maxResults=20,
            singleEvents=True,
            orderBy="startTime",
            timeZone="Europe/Kyiv",
        )
        .execute()
    )

    events = events_result.get("items", [])

    result = []

    for event in events:
        start = event.get("start", {})

        date_str = start.get("dateTime") or start.get("date")

        if not date_str:
            continue

        dt = parser.parse(date_str)

        result.append(
            {
                "summary": event.get("summary"),
                "start": dt.strftime("%d-%m-%Y"),
                "description": event.get("description"),
            }
        )
    print(result)

    return result


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out"}


@app.get("/", response_class=HTMLResponse)
async def ui(request: Request):
    user = request.session.get("user")

    if not user:
        return RedirectResponse(url="/login")

    return templates.TemplateResponse("index.html", {"request": request, "user": user})
