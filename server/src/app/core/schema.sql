-- Enable extension for UUID generation (PostgreSQL 13+)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE s3_status_enum AS ENUM (
    'PENDING',
    'PROCESSING',
    'READY',
    'FAILED'
);

CREATE TYPE rating_enum AS ENUM (
    'LIKE',
    'DISLIKE',
    'NEUTRAL'
);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- User Accounts & Auth
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    date_of_birth DATE,
    state VARCHAR(2), -- e.g., 'CA', 'NY'
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Artist Metadata
CREATE TABLE artists (
    id BIGSERIAL PRIMARY KEY,
    browse_id VARCHAR(255) UNIQUE NOT NULL, -- YouTube Music browseId
    name VARCHAR(255) NOT NULL,
    thumbnail_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Album Metadata
CREATE TABLE albums (
    id BIGSERIAL PRIMARY KEY,
    browse_id VARCHAR(255) UNIQUE NOT NULL, -- YouTube Music browseId
    title VARCHAR(255) NOT NULL,
    album_type VARCHAR(50), -- e.g., 'Album', 'Single', 'EP'
    thumbnail_url TEXT,
    release_year VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Track Catalog & S3 State
CREATE TABLE tracks (
    id BIGSERIAL PRIMARY KEY,
    youtube_id VARCHAR(50) UNIQUE NOT NULL, -- YouTube videoId
    title VARCHAR(255) NOT NULL,
    album_id BIGINT REFERENCES albums(id) ON DELETE SET NULL,
    duration_seconds INTEGER NOT NULL CHECK (duration_seconds >= 0),
    song_genre VARCHAR(100),
    thumbnail_url TEXT,
    is_explicit BOOLEAN DEFAULT FALSE NOT NULL,
    s3_status s3_status_enum DEFAULT 'PENDING' NOT NULL,
    s3_key TEXT,
    s3_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Track <-> Artist (Many-to-Many Join Table)
CREATE TABLE track_artists (
    track_id BIGINT REFERENCES tracks(id) ON DELETE CASCADE,
    artist_id BIGINT REFERENCES artists(id) ON DELETE CASCADE,
    artist_order INTEGER DEFAULT 0 NOT NULL, -- 0 for primary, 1+ for featured
    PRIMARY KEY (track_id, artist_id)
);

-- Current Explicit Feedback State (Fast UI Status Lookup)
CREATE TABLE user_track_likes (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    track_id BIGINT REFERENCES tracks(id) ON DELETE CASCADE,
    rating rating_enum NOT NULL DEFAULT 'NEUTRAL',
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    PRIMARY KEY (user_id, track_id)
);

-- Unified Playback History & ML Session Telemetry Log
CREATE TABLE user_playback_history (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    track_id BIGINT REFERENCES tracks(id) ON DELETE CASCADE NOT NULL,
    played_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    played_duration_seconds INTEGER DEFAULT 0 NOT NULL CHECK (played_duration_seconds >= 0),
    completion_rate REAL DEFAULT 0.0 NOT NULL CHECK (completion_rate >= 0.0 AND completion_rate <= 1.0),
    was_skipped BOOLEAN DEFAULT FALSE NOT NULL,
    number_of_pauses INTEGER DEFAULT 0 NOT NULL CHECK (number_of_pauses >= 0),
    replay_count INTEGER DEFAULT 0 NOT NULL CHECK (replay_count >= 0),
    like_status_at_play rating_enum DEFAULT 'NEUTRAL' NOT NULL,
    source_context VARCHAR(50) -- e.g., 'SEARCH', 'RECOMMENDATION', 'QUEUE', 'ALBUM'
);


CREATE TRIGGER update_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_track_likes_updated_at
BEFORE UPDATE ON user_track_likes
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ==========================================
-- 5. INDEXES FOR PERFORMANCE & ML
-- ==========================================

-- Quick chronological history lookups for user profiles ("Recently Played")
CREATE INDEX idx_playback_history_user_time 
ON user_playback_history (user_id, played_at DESC);

-- Rapid lookup for song performance and recommendation aggregations
CREATE INDEX idx_playback_history_track 
ON user_playback_history (track_id);

-- Lookup S3 status quickly during stream requests
CREATE INDEX idx_tracks_s3_status 
ON tracks (s3_status);

-- Foreign key indexes for join efficiency
CREATE INDEX idx_tracks_album_id 
ON tracks (album_id);

CREATE INDEX idx_track_artists_artist_id 
ON track_artists (artist_id);