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

logger = logging.getLogger("StreamingMusicAPI")
logging.basicConfig(level=logging.INFO)


class StreamingMusicAPI:
    def __init__(
        self,
        db_execute_fn: Callable[[str, tuple], Awaitable[Any]],
        s3_bucket_name: Optional[str] = None,
        aws_region: Optional[str] = None,
        hls_temp_dir: Optional[str] = None,
    ):
        """
        :param db_execute_fn: Async function to execute write SQL queries (e.g., await db_execute_fn(sql, params))
        :param s3_bucket_name: Name of the AWS S3 or Cloudflare R2 bucket
        :param aws_region: AWS Region
        :param hls_temp_dir: Base local path for temporary HLS chunk processing
        """
        self.db_execute = db_execute_fn
        self.s3_bucket_name = s3_bucket_name or os.getenv("S3_BUCKET_NAME", "my-music-locker")
        self.aws_region = aws_region or os.getenv("AWS_REGION", "us-east-2")
        self.hls_temp_dir = Path(hls_temp_dir or os.getenv("HLS_TEMP_DIR", "/tmp/hls_processing"))
        self.hls_temp_dir.mkdir(parents=True, exist_ok=True)

        # Initialize Boto3 S3 Client
        self.s3_client = boto3.client(
            "s3",
            region_name=self.aws_region,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )

        self.youtube_base_url = "https://www.youtube.com/watch?v="

    
    async def resolve_track_stream(self, youtube_id: str, background_tasks: Any) -> Dict[str, Any]:
        """
        Main entry point for client song requests.
        Returns S3 URL if present, or direct YT CDN URL + launches background S3 ingestion.
        """
        # 1. Query Database to check if the track exists in S3
        sql_check = """
            SELECT youtube_id, title, artist, is_in_s3 
            FROM tracks 
            WHERE youtube_id = %s;
        """
        track = await self.db_fetch_one(sql_check, (youtube_id,))

        # 2. CASE A: Song exists in S3 and flag is TRUE
        if track and track.get("is_in_s3"):
            logger.info(f"Track {youtube_id} found in S3. Generating S3 URL.")
            s3_key = f"tracks/{youtube_id}/playlist.m3u8"
            s3_url = self.generate_s3_url(s3_key, presigned=True)
            return {
                "source": "s3",
                "status": "ready",
                "stream_url": s3_url,
                "metadata": track
            }

        # 3. CASE B: Song NOT in S3 (or marked is_in_s3 = False)
        logger.info(f"Track {youtube_id} miss in S3. Fetching direct YouTube CDN URL.")
        
        # Extract live CDN streaming URL asynchronously (< 400ms)
        cdn_stream_url, metadata = await self.get_direct_youtube_cdn_url(youtube_id)

        # Trigger background processing task to generate HLS, upload to S3, and update DB
        background_tasks.add_task(
            self.process_and_upload_hls,
            youtube_id=youtube_id,
            metadata=metadata
        )

        # Return live stream URL immediately so AVQueuePlayer plays without delay
        return {
            "source": "youtube_cdn",
            "status": "buffering_to_s3",
            "stream_url": cdn_stream_url,
            "metadata": metadata
        }

    async def get_direct_youtube_cdn_url(self, youtube_id: str) -> tuple[str, Dict[str, Any]]:
        """
        Uses yt-dlp asynchronously to extract direct Google CDN URL + basic metadata.
        """
        youtube_url = f"{self.youtube_base_url}{youtube_id}"
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
        }

        def _extract():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                return info.get('url'), {
                    'youtube_id': youtube_id,
                    'title': info.get('title', 'Unknown Title'),
                    'artist': info.get('uploader', 'Unknown Artist'),
                    'duration': info.get('duration', 0),
                }

        # Run blocking yt-dlp network extraction in a thread pool
        return await asyncio.to_thread(_extract)

    async def process_and_upload_hls(self, youtube_id: str, metadata: Dict[str, Any]) -> None:
        """
        Background Task:
        1. Creates isolated unique local directory (batch safe).
        2. Transcodes audio to HLS (.m3u8 + .ts chunks) via FFmpeg.
        3. Uploads directory contents to S3.
        4. Updates DB flag `is_in_s3 = True`. ** Adjust this to fit schema 
        5. Wipes local temporary directory.
        """
        # Create an isolated unique folder for this specific processing batch
        job_id = uuid.uuid4().hex[:8]
        job_dir = self.hls_temp_dir / f"{youtube_id}_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)

        s3_prefix = f"tracks/{youtube_id}"
        playlist_file = job_dir / "playlist.m3u8"
        youtube_url = f"{self.youtube_base_url}{youtube_id}"

        logger.info(f"Starting background HLS generation for {youtube_id} in {job_dir}")

        try:
            # 1. Execute yt-dlp piped to FFmpeg asynchronously
            cmd = [
                "yt-dlp",
                "-f", "bestaudio/best",
                "--external-downloader", "ffmpeg",
                "--external-downloader-args",
                f"ffmpeg:-loglevel error -vn -c:a aac -b:a 192k -hls_time 4 -hls_list_size 0 -hls_segment_filename seq_%03d.ts",
                "-o", str(playlist_file),
                youtube_url
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=job_dir, # Runs the execution inside this working dir 
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"FFmpeg/yt-dlp error for {youtube_id}: {stderr.decode()}")
                return

            # 2. Upload all generated files (.m3u8 & .ts) to S3 concurrently/in thread
            logger.info(f"Uploading HLS chunks to S3 under prefix: {s3_prefix}")
            await asyncio.to_thread(self._upload_folder_to_s3, job_dir, s3_prefix)

            # 3. Upsert PostgreSQL record setting is_in_s3 = TRUE
            sql_upsert = """
                INSERT INTO tracks (youtube_id, title, artist, duration, s3_prefix, is_in_s3, updated_at)
                VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
                ON CONFLICT (youtube_id) 
                DO UPDATE SET 
                    is_in_s3 = TRUE,
                    title = EXCLUDED.title,
                    artist = EXCLUDED.artist,
                    updated_at = NOW();
            """
            await self.db_execute(
                sql_upsert,
                (
                    youtube_id,
                    metadata.get("title"),
                    metadata.get("artist"),
                    metadata.get("duration"),
                    s3_prefix
                )
            )
            logger.info(f"Successfully processed, uploaded, and updated DB for track {youtube_id}")

        except Exception as e:
            logger.error(f"Failed background processing for {youtube_id}: {str(e)}")

        finally:
            # 4. ALWAYS wipe local temporary folder to prevent storage leaks
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)
                logger.info(f"Cleaned up local temp directory: {job_dir}")

    def _upload_folder_to_s3(self, local_dir: Path, s3_prefix: str) -> None:
        """
        Synchronous helper to upload all files in a folder to S3.
        Executed inside asyncio.to_thread.
        """
        for file_path in local_dir.glob("*"):
            if file_path.is_file():
                s3_key = f"{s3_prefix}/{file_path.name}"
                
                # Determine Content-Type for proper browser/AVPlayer rendering
                content_type = "application/x-mpegURL" if file_path.suffix == ".m3u8" else "video/MP2T"

                self.s3_client.upload_file(
                    Filename=str(file_path),
                    Bucket=self.s3_bucket_name,
                    Key=s3_key,
                    ExtraArgs={"ContentType": content_type}
                )

    def generate_s3_url(self, s3_key: str, presigned: bool = True, expires_in: int = 3600) -> str:
        """
        Generates either a presigned URL or direct public S3 URL for a given object key.
        """
        if presigned:
            try:
                return self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': self.s3_bucket_name, 'Key': s3_key},
                    ExpiresIn=expires_in
                )
            except (BotoCoreError, ClientError) as e:
                logger.error(f"Error generating presigned URL: {e}")
                raise

        return f"https://{self.s3_bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"