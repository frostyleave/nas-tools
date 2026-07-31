ALTER TABLE INDEXER_SITES DROP COLUMN RENDER;
ALTER TABLE INDEXER_SITES DROP COLUMN PROXY;
ALTER TABLE INDEXER_SITES DROP COLUMN SOURCE_TYPE;
ALTER TABLE INDEXER_SITES DROP COLUMN BROWSE;
ALTER TABLE INDEXER_SITES DROP COLUMN SEARCH_TYPE;
ALTER TABLE CONFIG_SITE DROP COLUMN EXCLUDE;
ALTER TABLE CONFIG_SITE DROP COLUMN SIZE;

UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": false, "proxy": false, "en_expand": false, "source_type": "ANIME"}' WHERE "ID" = 'acgrip';
UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": false, "proxy": false, "en_expand": false, "source_type": "ANIME"}' WHERE "ID" = 'comicat';
UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": false, "proxy": false, "en_expand": false, "source_type": "ANIME"}' WHERE "ID" = 'dmhy';
UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": false, "proxy": false, "en_expand": false, "source_type": "ANIME"}' WHERE "ID" = 'mikanani';
UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": false, "proxy": false, "en_expand": false, "search_param": "en", "source_type": "ANIME"}' WHERE "ID" = 'nyaa';
UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": false, "proxy": false, "en_expand": false, "search_param": "en", "source_type": "TV"}' WHERE "ID" = 'eztv';
UPDATE "INDEXER_SITES" SET "EXTRA" = '{"render": true, "proxy": true, "en_expand": false, "search_param": "imdb", "source_type": "MOVIE"}' WHERE "ID" = 'torrentgalaxy';