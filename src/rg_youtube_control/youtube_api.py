import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
KEYRING_SERVICE = "RG YouTube Control"

@dataclass
class YouTubeProfile:
    name: str
    channel_id: str
    channel_title: str

class YouTubeClient:
    def __init__(self, profile: str = "default") -> None:
        self.profile = profile
        self._service = None

    def authorize(self, client_secret_path: str | Path) -> YouTubeProfile:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
        creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
        keyring.set_password(KEYRING_SERVICE, self.profile, creds.to_json())
        self._service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        channel = self.my_channel()
        return YouTubeProfile(
            name=self.profile,
            channel_id=channel["id"],
            channel_title=channel["snippet"]["title"],
        )

    def clear_credentials(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, self.profile)
        except keyring.errors.PasswordDeleteError:
            pass
        self._service = None

    def credentials(self) -> Credentials:
        raw = keyring.get_password(KEYRING_SERVICE, self.profile)
        if not raw:
            raise RuntimeError("YouTube authorization is not configured")
        creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            keyring.set_password(KEYRING_SERVICE, self.profile, creds.to_json())
        return creds

    def service(self):
        if self._service is None:
            self._service = build(
                "youtube", "v3", credentials=self.credentials(), cache_discovery=False
            )
        return self._service

    def my_channel(self) -> dict[str, Any]:
        response = self.service().channels().list(
            part="snippet,contentDetails", mine=True, maxResults=50
        ).execute()
        items = response.get("items", [])
        if not items:
            raise RuntimeError("No YouTube channel is available for this authorization")
        return items[0]

    def recent_videos(self, limit: int = 50) -> list[dict[str, Any]]:
        channel = self.my_channel()
        uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
        items: list[dict[str, Any]] = []
        token = None
        while len(items) < limit:
            response = self.service().playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads,
                maxResults=min(50, limit - len(items)),
                pageToken=token,
            ).execute()
            items.extend(response.get("items", []))
            token = response.get("nextPageToken")
            if not token:
                break
        ids = [x["contentDetails"]["videoId"] for x in items]
        return self.video_details(ids)

    def video_details(self, video_ids: list[str]) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        result: list[dict[str, Any]] = []
        for pos in range(0, len(video_ids), 50):
            response = self.service().videos().list(
                part="snippet,status,contentDetails,statistics",
                id=",".join(video_ids[pos:pos + 50]),
            ).execute()
            result.extend(response.get("items", []))
        return result

    def comment_threads(
        self, video_id: str, moderation_status: str = "published", limit: int = 100
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        token = None
        while len(result) < limit:
            response = self.service().commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                moderationStatus=moderation_status,
                textFormat="plainText",
                order="time",
                maxResults=min(100, limit - len(result)),
                pageToken=token,
            ).execute()
            result.extend(response.get("items", []))
            token = response.get("nextPageToken")
            if not token:
                break
        return result

    def replies(self, parent_comment_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        token = None
        while True:
            response = self.service().comments().list(
                part="snippet",
                parentId=parent_comment_id,
                textFormat="plainText",
                maxResults=100,
                pageToken=token,
            ).execute()
            result.extend(response.get("items", []))
            token = response.get("nextPageToken")
            if not token:
                return result

    def reply(self, parent_comment_id: str, text: str) -> dict[str, Any]:
        body = {"snippet": {"parentId": parent_comment_id, "textOriginal": text}}
        return self.service().comments().insert(part="snippet", body=body).execute()

    def set_moderation(
        self, comment_id: str, status: str, ban_author: bool = False
    ) -> None:
        request = self.service().comments().setModerationStatus(
            id=comment_id,
            moderationStatus=status,
            banAuthor=bool(ban_author and status == "rejected"),
        )
        request.execute()

    def update_video(
        self,
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.service().videos().list(part="snippet", id=video_id).execute()
        items = current.get("items", [])
        if not items:
            raise RuntimeError(f"Video not found: {video_id}")
        snippet = items[0]["snippet"]
        if title is not None:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        return self.service().videos().update(
            part="snippet", body={"id": video_id, "snippet": snippet}
        ).execute()