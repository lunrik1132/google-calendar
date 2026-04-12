import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from datetime import datetime
from dateutil import parser
from google.auth.transport.requests import Request as GoogleRequest

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY", "dev_secret")
redirect_uri = os.getenv("REDIRECT_URI")

app = FastAPI()


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    same_site="lax",
    https_only=True,
)

oauth = OAuth()

oauth.register(
    name="google",
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile https://www.googleapis.com/auth/calendar",
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
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
    redirect_uri = "https://google-calendar-qp97.onrender.com/auth/callback"
    # redirect_uri = "http://127.0.0.1:8000/auth/callback"

    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        access_type="offline",
        prompt="consent",
    )


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)

    userinfo = token.get("userinfo")

    if not userinfo:
        userinfo = {}

    request.session["token"] = {
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "id_token": token.get("id_token"),
    }

    request.session["user"] = {
        "name": userinfo.get("name"),
        "email": userinfo.get("email"),
        "picture": userinfo.get("picture"),
    }

    return RedirectResponse("/")


@app.get("/events")
async def get_events(request: Request):
    token = request.session.get("token")
    print("TOKEN:", token)
    if not token:
        return RedirectResponse(url="/login")

    # try:
    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
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
                "id": event.get("id"),
                "summary": event.get("summary"),
                "start": dt.strftime("%d-%m-%Y"),
                "description": event.get("description"),
            }
        )
    print(result)

    return result
    # except Exception:
    #     return JSONResponse({"error": "auth_expired"}, status_code=401)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out"}


@app.get("/")
async def ui(request: Request):
    token = request.session.get("token")

    if not token or not isinstance(token, dict):
        return RedirectResponse("/login")

    return FileResponse("templates/index.html")


@app.get("/health")
async def health():
    return "OK"


@app.delete("/events/{event_id}")
async def delete_event(event_id: str, request: Request):
    token = request.session.get("token")

    if not token:
        return JSONResponse({"error": "not_authenticated"}, status_code=401)

    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )

    service = build("calendar", "v3", credentials=creds)

    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()

        return {"status": "deleted"}

    except Exception:
        return JSONResponse({"error": "delete_failed"}, status_code=500)


@app.put("/events/{event_id}")
async def update_event(event_id: str, request: Request):
    token = request.session.get("token")
    body = await request.json()

    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )

    service = build("calendar", "v3", credentials=creds)

    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        event["summary"] = body.get("summary")
        event["description"] = body.get("description")

        if body.get("date"):
            event["start"] = {"date": body["date"]}
            event["end"] = {"date": body["date"]}

        updated_event = (
            service.events()
            .update(calendarId="primary", eventId=event_id, body=event)
            .execute()
        )

        return {"status": "updated"}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/events")
async def create_event(request: Request):
    token = request.session.get("token")
    body = await request.json()

    creds = Credentials(
        token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )

    service = build("calendar", "v3", credentials=creds)

    try:
        event = {
            "summary": body.get("summary"),
            "description": body.get("description"),
            "start": {"date": body.get("date")},
            "end": {"date": body.get("date")},
        }

        created_event = (
            service.events().insert(calendarId="primary", body=event).execute()
        )

        return {"status": "created", "id": created_event["id"]}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
