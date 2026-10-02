import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
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
        self._analytics_service = None
        self._reporting_service = None

    def authorize(self, client_secret_path: str | Path) -> YouTubeProfile:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
        creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=True)
        keyring.set_password(KEYRING_SERVICE, self.profile, creds.to_json())
        self._service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        self._analytics_service = None
        self._reporting_service = None
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
        self._analytics_service = None
        self._reporting_service = None

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

    def analytics_service(self):
        if self._analytics_service is None:
            self._analytics_service = build(
                "youtubeAnalytics",
                "v2",
                credentials=self.credentials(),
                cache_discovery=False,
            )
        return self._analytics_service

    def analytics_report(
        self,
        *,
        start_date: str,
        end_date: str,
        metrics: str,
        dimensions: str | None = None,
        filters: str | None = None,
        sort: str | None = None,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
        }
        if dimensions:
            params["dimensions"] = dimensions
        if filters:
            params["filters"] = filters
        if sort:
            params["sort"] = sort
        if max_results:
            params["maxResults"] = max_results
        return self.analytics_service().reports().query(**params).execute()

    def reporting_service(self):
        if self._reporting_service is None:
            self._reporting_service = build(
                "youtubereporting",
                "v1",
                credentials=self.credentials(),
                cache_discovery=False,
            )
        return self._reporting_service

    def reach_job(self) -> dict[str, Any] | None:
        response = self.reporting_service().jobs().list().execute()
        for job in response.get("jobs", []):
            if job.get("reportTypeId") == "channel_reach_basic_a1":
                return job
        return None

    def ensure_reach_job(self) -> tuple[dict[str, Any], bool]:
        existing = self.reach_job()
        if existing is not None:
            return existing, False
        created = self.reporting_service().jobs().create(
            body={
                "reportTypeId": "channel_reach_basic_a1",
                "name": "RG YouTube Control Reach",
            }
        ).execute()
        return created, True

    def reach_report_rows(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
        job = self.reach_job()
        if job is None:
            return [], None

        rows: list[dict[str, str]] = []
        token = None
        service = self.reporting_service()
        session = AuthorizedSession(self.credentials())
        while True:
            request = service.jobs().reports().list(
                jobId=job["id"],
                pageSize=1000,
                pageToken=token,
            )
            response = request.execute()
            for report in response.get("reports", []):
                report_start = str(report.get("startTime") or "")[:10]
                report_end = str(report.get("endTime") or "")[:10]
                if report_start and report_start > end_date:
                    continue
                if report_end and report_end < start_date:
                    continue
                download_url = report.get("downloadUrl")
                if not download_url:
                    continue
                downloaded = session.get(download_url, timeout=60)
                downloaded.raise_for_status()
                reader = csv.DictReader(io.StringIO(downloaded.text))
                for row in reader:
                    day = str(row.get("date") or "")
                    if day and (day < start_date or day > end_date):
                        continue
                    rows.append({str(k): str(v) for k, v in row.items()})
            token = response.get("nextPageToken")
            if not token:
                break
        return rows, job

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


    def caption_tracks(self, video_id: str) -> list[dict[str, Any]]:
        response = self.service().captions().list(
            part="snippet",
            videoId=video_id,
        ).execute()
        return response.get("items", [])

    def download_caption_srt(self, caption_id: str) -> str:
        request = self.service().captions().download(
            id=caption_id,
            tfmt="srt",
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buffer.getvalue().decode("utf-8-sig", errors="replace")

    def best_caption_track(
        self,
        video_id: str,
        preferred_languages: tuple[str, ...] = ("ru", "uk", "en"),
    ) -> dict[str, Any] | None:
        tracks = self.caption_tracks(video_id)
        if not tracks:
            return None

        def score(item: dict[str, Any]) -> tuple[int, int, int, str]:
            snippet = item.get("snippet", {})
            language = str(snippet.get("language") or "").lower()
            status = str(snippet.get("status") or "")
            track_kind = str(snippet.get("trackKind") or "")
            is_draft = bool(snippet.get("isDraft"))
            lang_score = 0
            for index, preferred in enumerate(preferred_languages):
                if language == preferred or language.startswith(preferred + "-"):
                    lang_score = len(preferred_languages) - index
                    break
            serving_score = 2 if status == "serving" else 0
            manual_score = 1 if track_kind != "ASR" else 0
            draft_penalty = -10 if is_draft else 0
            return (
                lang_score + draft_penalty,
                serving_score,
                manual_score,
                str(snippet.get("lastUpdated") or ""),
            )

        return max(tracks, key=score)

    def download_best_caption_srt(
        self,
        video_id: str,
        preferred_languages: tuple[str, ...] = ("ru", "uk", "en"),
    ) -> tuple[dict[str, Any], str]:
        track = self.best_caption_track(video_id, preferred_languages)
        if track is None:
            raise RuntimeError("Для цього відео не знайдено доступних субтитрів.")
        text = self.download_caption_srt(track["id"])
        return track, text