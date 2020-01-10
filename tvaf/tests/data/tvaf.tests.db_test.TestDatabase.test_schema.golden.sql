
PRAGMA page_size=4096;

BEGIN TRANSACTION;

DROP TABLE IF EXISTS audit;
CREATE TABLE audit (origin text not null, tracker text not null collate nocase, infohash text not null collate nocase, generation int not null, num_bytes int not null default 0, atime int not null default 0);
CREATE UNIQUE INDEX audit_on_tracker_infohash_origin_generation on audit (tracker, infohash, origin, generation);

DROP TABLE IF EXISTS file;
CREATE TABLE file (infohash text not null collate nocase, file_index int not null, path text not null, start int not null, stop int not null);
CREATE UNIQUE INDEX file_on_infohash_file_index on file (infohash, file_index);

DROP TABLE IF EXISTS request;
CREATE TABLE request (request_id integer primary key autoincrement, tracker text not null, torrent_id text not null, infohash text not null collate nocase, start int not null, stop int not null, origin text not null, random bool not null default 0, readahead bool not null default 0, priority int not null, time int not null, deactivated_at int);
CREATE INDEX request_on_infohash on request (infohash);

DROP TABLE IF EXISTS torrent_meta;
CREATE TABLE torrent_meta (infohash text primary key collate nocase, generation int not null default 0, managed bool not null default 0, atime int not null default 0);

DROP TABLE IF EXISTS torrent_status;
CREATE TABLE torrent_status (infohash text primary key collate nocase, tracker text not null collate nocase, piece_bitmap blob not null, piece_length int not null, length int not null, seeders int not null, leechers int not null, announce_message text);

COMMIT TRANSACTION;
