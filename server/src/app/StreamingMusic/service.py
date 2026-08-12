import os
import shutil
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Awaitable
import boto3
from botocore.exceptions import BotoCoreError, ClientError
import yt_dlp

from app.streamingMusic.models import S3Status, StreamResponseModel, TrackStatusResponse, DeleteTrackResponse

logger = logging.getLogger("StreamingMusicAPI")
logging.basicConfig(level=logging.INFO)


class StreamingMusicAPI:
    def __init__(
        self,
        db_execute_fn: Callable[[str, tuple], Awaitable[Any]],
        db_fetch_one_fn: Callable[[str, tuple], Awaitable[Optional[Dict[str, Any]]]],
        s3_bucket_name: Optional[str] = None,
        aws_region: Optional[str] = None,
        hls_temp_dir: Optional[str] = None,
    ):
        self.db_execute = db_execute_fn
        self.db_fetch_one = db_fetch_one_fn

        self.s3_bucket_name = s3_bucket_name or os.getenv("S3_BUCKET_NAME", "my-music-locker")
        self.aws_region = aws_region or os.getenv("AWS_REGION", "us-east-1")
        self.hls_temp_dir = Path(hls_temp_dir or os.getenv("HLS_TEMP_DIR", "/tmp/hls_processing"))
        self.hls_temp_dir.mkdir(parents=True, exist_ok=True)

        self.s3_client = boto3.client(
            "s3",
            region_name=self.aws_region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

        self.youtube_base_url = "https://www.youtube.com/watch?v="

    async def resolve_track_stream(self, youtube_id: str, background_tasks: Any) -> StreamResponseModel:
        """
        Main entry point for stream requests.
        Handles status checks (READY, PROCESSING, NOT_CACHED, FAILED).
        """
        sql_check = """
            SELECT youtube_id, title, artist, duration, s3_status 
            FROM tracks 
            WHERE youtube_id = %s;
        """
        track = await self.db_fetch_one(sql_check, (youtube_id,))
        current_status = track.get("s3_status") if track else S3Status.NOT_CACHED

        # 1. CASE: Track is completely READY in S3
        if current_status == S3Status.READY:
            logger.info(f"Track {youtube_id} READY in S3. Generating S3 URL.")
            s3_key = f"tracks/{youtube_id}/playlist.m3u8"
            s3_url = self.generate_s3_url(s3_key, presigned=True)
            return StreamResponseModel(
                source="s3",
                s3_status=S3Status.READY,
                stream_url=s3_url,
                metadata=track
            )

        # 2. CASE: Track is currently PROCESSING in background (don't spawn duplicate background job)
        if current_status == S3Status.PROCESSING:
            logger.info(f"Track {youtube_id} is already PROCESSING. Returning live CDN stream.")
            cdn_url, metadata = await self.get_direct_youtube_cdn_url(youtube_id)
            return StreamResponseModel(
                source="youtube_cdn",
                s3_status=S3Status.PROCESSING,
                stream_url=cdn_url,
                metadata=metadata
            )

        # 3. CASE: NOT_CACHED or FAILED -> Trigger fresh ingestion task
        logger.info(f"Track {youtube_id} status: {current_status}. Launching background S3 ingestion.")
        cdn_url, metadata = await self.get_direct_youtube_cdn_url(youtube_id)

        # Update DB state to PROCESSING immediately before task runs
        sql_processing = """
            INSERT INTO tracks (youtube_id, title, artist, duration, s3_status, updated_at)
            VALUES (%s, %s, %s, %s, 'PROCESSING', NOW())
            ON CONFLICT (youtube_id) 
            DO UPDATE SET s3_status = 'PROCESSING', updated_at = NOW();
        """
        await self.db_execute(
            sql_processing, 
            (youtube_id, metadata.get("title"), metadata.get("artist"), metadata.get("duration"))
        )

        # Add ingestion job to FastAPI background tasks
        background_tasks.add_task(
            self.process_and_upload_hls,
            youtube_id=youtube_id,
            metadata=metadata
        )

        return StreamResponseModel(
            source="youtube_cdn",
            s3_status=S3Status.PROCESSING,
            stream_url=cdn_url,
            metadata=metadata
        )

    async def get_track_status(self, youtube_id: str) -> TrackStatusResponse:
        """
        Queries DB for current track processing status.
        """
        sql = "SELECT youtube_id, title, artist, duration, s3_status FROM tracks WHERE youtube_id = %s;"
        track = await self.db_fetch_one(sql, (youtube_id,))
        
        if not track:
            return TrackStatusResponse(youtube_id=youtube_id, s3_status=S3Status.NOT_CACHED, metadata=None)

        return TrackStatusResponse(
            youtube_id=youtube_id,
            s3_status=S3Status(track.get("s3_status", S3Status.NOT_CACHED)),
            metadata=track
        )

    async def delete_track_s3(self, youtube_id: str) -> DeleteTrackResponse:
        """
        Removes HLS chunks from S3 and resets s3_status = NOT_CACHED in DB.
        Does not delete track metadata record from Postgres.
        """
        s3_prefix = f"tracks/{youtube_id}/"

        # 1. Delete objects under prefix from S3 asynchronously
        await asyncio.to_thread(self._delete_s3_prefix, s3_prefix)

        # 2. Update DB status to NOT_CACHED
        sql_update = "UPDATE tracks SET s3_status = 'NOT_CACHED', updated_at = NOW() WHERE youtube_id = %s;"
        await self.db_execute(sql_update, (youtube_id,))

        logger.info(f"Successfully deleted S3 assets and updated status for track {youtube_id}")
        return DeleteTrackResponse(
            youtube_id=youtube_id,
            message=f"Successfully purged S3 cache for track {youtube_id}",
            s3_status=S3Status.NOT_CACHED
        )

    async def process_and_upload_hls(self, youtube_id: str, metadata: Dict[str, Any]) -> None:
        """
        Background Worker: Transcodes via FFmpeg, uploads to S3, updates DB state to READY or FAILED.
        """
        job_id = uuid.uuid4().hex[:8]
        job_dir = self.hls_temp_dir / f"{youtube_id}_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)

        s3_prefix = f"tracks/{youtube_id}"
        playlist_file = job_dir / "playlist.m3u8"
        youtube_url = f"{self.youtube_base_url}{youtube_id}"

        try:
            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "--external-downloader", "ffmpeg",
                "--external-downloader-args",
                f"ffmpeg:-loglevel error -vn -c:a aac -b:a 192k -hls_time 4 -hls_list_size 0 -hls_segment_filename {job_dir}/seq_%03d.ts",
                "-o", str(playlist_file),
                youtube_url
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"FFmpeg error for {youtube_id}: {stderr.decode()}")
                await self._mark_failed(youtube_id)
                return

            # Upload files to S3
            await asyncio.to_thread(self._upload_folder_to_s3, job_dir, s3_prefix)

            # Mark state = READY in DB
            sql_ready = """
                UPDATE tracks 
                SET s3_status = 'READY', s3_prefix = %s, updated_at = NOW() 
                WHERE youtube_id = %s;
            """
            await self.db_execute(sql_ready, (s3_prefix, youtube_id))
            logger.info(f"HLS upload complete for {youtube_id}. State set to READY.")

        except Exception as e:
            logger.error(f"HLS processing failed for {youtube_id}: {str(e)}")
            await self._mark_failed(youtube_id)

        finally:
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)

    async def _mark_failed(self, youtube_id: str):
        sql_fail = "UPDATE tracks SET s3_status = 'FAILED', updated_at = NOW() WHERE youtube_id = %s;"
        await self.db_execute(sql_fail, (youtube_id,))

    async def get_direct_youtube_cdn_url(self, youtube_id: str) -> tuple[str, Dict[str, Any]]:
        youtube_url = f"{self.youtube_base_url}{youtube_id}"
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True}

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                return info.get('url'), {
                    'youtube_id': youtube_id,
                    'title': info.get('title', 'Unknown Title'),
                    'artist': info.get('uploader', 'Unknown Artist'),
                    'duration': info.get('duration', 0),
                }

        return await asyncio.to_thread(_extract)

    def _upload_folder_to_s3(self, local_dir: Path, s3_prefix: str) -> None:
        for file_path in local_dir.glob("*"):
            if file_path.is_file():
                s3_key = f"{s3_prefix}/{file_path.name}"
                content_type = "application/x-mpegURL" if file_path.suffix == ".m3u8" else "video/MP2T"
                self.s3_client.upload_file(
                    Filename=str(file_path),
                    Bucket=self.s3_bucket_name,
                    Key=s3_key,
                    ExtraArgs={"ContentType": content_type}
                )

    def _delete_s3_prefix(self, s3_prefix: str) -> None:
        """
        Deletes all objects under an S3 folder prefix.
        """
        paginator = self.s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.s3_bucket_name, Prefix=s3_prefix)

        objects_to_delete = []
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects_to_delete.append({'Key': obj['Key']})

        if objects_to_delete:
            self.s3_client.delete_objects(
                Bucket=self.s3_bucket_name,
                Delete={'Objects': objects_to_delete}
            )

    def generate_s3_url(self, s3_key: str, presigned: bool = True, expires_in: int = 3600) -> str:
        if presigned:
            return self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.s3_bucket_name, 'Key': s3_key},
                ExpiresIn=expires_in
            )
        return f"https://{self.s3_bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"