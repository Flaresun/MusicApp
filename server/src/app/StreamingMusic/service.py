import os
import shutil
import uuid
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable, Awaitable, List
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

    async def get_track_status(self, youtube_id: str) -> dict:
        """
        Returns a dictionary shaped for the TrackStatusResponse Pydantic model.
        """
        sql = """
            SELECT s3_status, title, duration_seconds 
            FROM tracks 
            WHERE youtube_id = %s;
        """
        result = await self.db_execute(sql, (youtube_id,))
        
        if result and len(result) > 0:
            track = result[0]
            return {
                "youtube_id": youtube_id,
                "s3_status": track.get("s3_status"),
                "metadata": {
                    "title": track.get("title"),
                    "duration": track.get("duration_seconds")
                }
            }
        
        # Track not in database yet
        return {
            "youtube_id": youtube_id,
            "s3_status": "NOT_CACHED",
            "metadata": None
        }
    
    async def resolve_track_stream(self, youtube_id: str, client_metadata: dict, background_tasks: Any) -> dict:
        """
        Main entry point for client song requests using client-provided metadata.
        """
        # 1. Check current status in DB
        sql_check = "SELECT s3_status, s3_key, title FROM tracks WHERE youtube_id = %s;"
        result = await self.db_execute(sql_check, (youtube_id,))
        track = result[0] if result else None
        
        current_status = track.get("s3_status") if track else "NOT_CACHED"

        # 2. CASE A: Song is READY in S3
        if current_status == "READY" and track.get("s3_key"):
            logger.info(f"Track {youtube_id} is READY. Generating presigned S3 URL.")
            s3_url = self.generate_s3_url(track["s3_key"], presigned=True)
            return {
                "source": "s3",
                "s3_status": "READY",
                "stream_url": s3_url,
                "metadata": {"title": track.get("title")}
            }

        # 3. CASE B: Song is actively PROCESSING
        if current_status == "PROCESSING":
            logger.info(f"Track {youtube_id} is already PROCESSING. Bypassing background worker.")
            cdn_stream_url = await self.get_direct_youtube_cdn_url(youtube_id)
            return {
                "source": "youtube_cdn",
                "s3_status": "PROCESSING",
                "stream_url": cdn_stream_url,
                "metadata": client_metadata
            }

        # 4. CASE C: Song is NOT_CACHED, FAILED, or missing entirely
        logger.info(f"Track {youtube_id} status is {current_status}. Locking state and launching worker.")
        
        # Grab live CDN URL
        cdn_stream_url = await self.get_direct_youtube_cdn_url(youtube_id)
        
        generated_s3_key = f"tracks/{youtube_id}/playlist.m3u8"

        # Database Relational Inserts
        track_id = await self._upsert_track_record(youtube_id, client_metadata, generated_s3_key)
        await self._upsert_artists_and_link(track_id, client_metadata.get("artists", []))

        # Launch the background worker to handle the actual download
        background_tasks.add_task(
            self.process_and_upload_hls,
            youtube_id=youtube_id,
            s3_key_prefix=f"tracks/{youtube_id}"
        )

        return {
            "source": "youtube_cdn",
            "s3_status": "PROCESSING",
            "stream_url": cdn_stream_url,
            "metadata": client_metadata
        }
    
    async def get_direct_youtube_cdn_url(self, youtube_id: str) -> str:
        """
        Extracts just the fast CDN URL without parsing full metadata.
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
                return info.get('url')

        return await asyncio.to_thread(_extract)

    async def process_and_upload_hls(self, youtube_id: str, s3_key_prefix: str) -> None:
        """
        Background Worker: Transcodes to HLS, uploads, and marks READY (or FAILED on error).
        """
        job_id = uuid.uuid4().hex[:8]
        job_dir = self.hls_temp_dir / f"{youtube_id}_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        playlist_file = job_dir / "playlist.m3u8"
        youtube_url = f"{self.youtube_base_url}{youtube_id}"

        try:
            # 1. Download and transcode
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
                *cmd, cwd=job_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"FFmpeg/yt-dlp error: {stderr.decode()}")

            # 2. Upload to S3
            await asyncio.to_thread(self._upload_folder_to_s3, job_dir, s3_key_prefix)

            # 3. Success: Update DB to READY
            sql_success = "UPDATE tracks SET s3_status = 'READY' WHERE youtube_id = %s;"
            await self.db_execute(sql_success, (youtube_id,))
            logger.info(f"Successfully processed and uploaded HLS chunks for {youtube_id}")

        except Exception as e:
            # 4. Failure: Fallback to FAILED so it can be retried later
            logger.error(f"Failed processing track {youtube_id}: {str(e)}")
            sql_fail = "UPDATE tracks SET s3_status = 'FAILED' WHERE youtube_id = %s;"
            await self.db_execute(sql_fail, (youtube_id,))

        finally:
            # 5. Cleanup local storage
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)

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

    async def delete_track_s3(self, youtube_id: str) -> dict:
        """
        Deletes the HLS assets from S3 for a given track and updates the DB.
        Returns a dictionary matching the DeleteTrackResponse Pydantic model.
        """
        # 1. Verify track exists in the database
        sql_check = "SELECT s3_status, s3_key FROM tracks WHERE youtube_id = %s;"
        result = await self.db_execute(sql_check, (youtube_id,))
        
        if not result or len(result) == 0:
            raise ValueError(f"Track with youtube_id '{youtube_id}' not found in the database.")
        
        track = result[0]
        s3_key = track.get("s3_key")

        # 2. Delete the associated files from S3 if an S3 key exists
        if s3_key:
            # The s3_key is typically "tracks/{youtube_id}/playlist.m3u8"
            # We want to delete the entire "tracks/{youtube_id}/" prefix/folder.
            s3_prefix = f"tracks/{youtube_id}/"
            logger.info(f"Purging S3 assets for prefix: {s3_prefix}")
            
            # Execute the blocking S3 deletion in a thread
            await asyncio.to_thread(self._delete_s3_folder, s3_prefix)
        else:
            logger.info(f"No s3_key found for {youtube_id}. Skipping S3 deletion.")

        # 3. Update database status
        # Set s3_status to NOT_CACHED and nullify the s3_key so it doesn't leave stale data
        sql_update = """
            UPDATE tracks 
            SET s3_status = 'NOT_CACHED', s3_key = NULL 
            WHERE youtube_id = %s;
        """
        await self.db_execute(sql_update, (youtube_id,))
        logger.info(f"Database updated: Track {youtube_id} is now NOT_CACHED.")

        # 4. Return response matching DeleteTrackResponse model
        return {
            "youtube_id": youtube_id,
            "message": "S3 cache successfully purged and database updated.",
            "s3_status": "NOT_CACHED"
        }

    def _delete_s3_folder(self, s3_prefix: str) -> None:
        """
        Synchronous helper to completely delete an S3 "folder" (all objects with a given prefix).
        S3 doesn't have true folders, so we must list and delete all matching objects.
        Executed inside asyncio.to_thread.
        """
        paginator = self.s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=self.s3_bucket_name, Prefix=s3_prefix)

        delete_us = {'Objects': []}
        
        for item in pages.search('Contents'):
            if item:
                delete_us['Objects'].append({'Key': item['Key']})

                # S3 delete_objects API has a hard limit of 1000 objects per request.
                # Flush the batch if we hit that limit (unlikely for a single song, but safe).
                if len(delete_us['Objects']) >= 1000:
                    self.s3_client.delete_objects(Bucket=self.s3_bucket_name, Delete=delete_us)
                    delete_us = {'Objects': []}

        # Flush any remaining objects
        if len(delete_us['Objects']) > 0:
            self.s3_client.delete_objects(Bucket=self.s3_bucket_name, Delete=delete_us)


    async def _upsert_track_record(self, youtube_id: str, meta: dict, s3_key: str) -> int:
        """
        Upserts the track into the `tracks` table and locks status to PROCESSING.
        Validates the database output strictly. Raises RuntimeError on failure.
        """
        sql_upsert = """
            INSERT INTO tracks (youtube_id, title, duration_seconds, thumbnail_url, s3_status, s3_key)
            VALUES (%s, %s, %s, %s, 'PROCESSING', %s)
            ON CONFLICT (youtube_id) 
            DO UPDATE SET 
                s3_status = 'PROCESSING',
                s3_key = EXCLUDED.s3_key,
                title = EXCLUDED.title,
                duration_seconds = EXCLUDED.duration_seconds,
                thumbnail_url = EXCLUDED.thumbnail_url
            RETURNING id;
        """
        try:
            result = await self.db_execute(
                sql_upsert, 
                (
                    youtube_id, 
                    meta["title"], 
                    meta["duration_seconds"], 
                    meta["thumbnail_url"], 
                    s3_key
                )
            )
        except Exception as e:
            raise RuntimeError(f"Database execution failed during track upsert for {youtube_id}: {str(e)}")

        # Strict validation of the RETURNING clause output
        if not result or not isinstance(result, list) or len(result) == 0:
            raise RuntimeError(f"Database failed to return a row after upserting track {youtube_id}")

        track_id = result[0].get("id")
        if not track_id:
            raise RuntimeError(f"Database row missing 'id' field after upserting track {youtube_id}")

        return track_id

    async def _upsert_artists_and_link(self, track_id: int, artists: List[dict]) -> None:
        """
        Upserts each artist into the `artists` table and creates Many-to-Many links in `track_artists`.
        Uses best-effort logic: skips individual artists on failure to prevent stream crashing.
        """
        for index, artist in enumerate(artists):
            browse_id = artist.get("browse_id")
            name = artist.get("name")
            
            if not browse_id or not name:
                logger.warning(f"Artist payload missing required fields for track ID {track_id}. Skipping artist: {artist}")
                continue

            try:
                # 1. Upsert Artist
                artist_sql = """
                    INSERT INTO artists (browse_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (browse_id)
                    DO UPDATE SET name = EXCLUDED.name
                    RETURNING id;
                """
                artist_res = await self.db_execute(artist_sql, (browse_id, name))
                
                # Validation: Skip this artist if the DB acts weirdly instead of crashing
                if not artist_res or not isinstance(artist_res, list) or len(artist_res) == 0:
                    logger.error(f"Database returned empty result when upserting artist '{name}' ({browse_id}). Skipping link.")
                    continue
                    
                artist_id = artist_res[0].get("id")
                if not artist_id:
                    logger.error(f"Missing internal 'id' for artist '{name}' ({browse_id}). Skipping link.")
                    continue

                # 2. Link Track and Artist
                link_sql = """
                    INSERT INTO track_artists (track_id, artist_id, artist_order)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (track_id, artist_id) DO NOTHING;
                """
                await self.db_execute(link_sql, (track_id, artist_id, index))
                
            except Exception as e:
                # Option B: Catch errors per artist so the rest of the stream continues
                logger.error(f"Failed to process artist '{name}' ({browse_id}) for track {track_id}: {str(e)}")
                continue