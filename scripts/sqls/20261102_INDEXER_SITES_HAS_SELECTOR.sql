UPDATE INDEXER_SITES SET TORRENTS = REPLACE(TORRENTS, ':has(\"table.torrentname\")', ':has(table.torrentname)') WHERE TORRENTS LIKE '%:has(\"table.torrentname\")%';
UPDATE INDEXER_SITES SET TORRENTS = REPLACE(TORRENTS, ':has(\"td.rowfollow\")', ':has(td.rowfollow)') WHERE TORRENTS LIKE '%:has(\"td.rowfollow\")%';
UPDATE INDEXER_SITES SET TORRENTS = REPLACE(TORRENTS, ':has(\"a[title]\")', ':has(a[title])') WHERE TORRENTS LIKE '%:has(\"a[title]\")%';
UPDATE INDEXER_SITES SET TORRENTS = REPLACE(TORRENTS, ':has(\"a[href]\")', ':has(a[href])') WHERE TORRENTS LIKE '%:has(\"a[href]\")%';
UPDATE INDEXER_SITES SET TORRENTS = REPLACE(TORRENTS, ':has(\"a[href*=''details.php?id='']\")', ':has(a[href*=''details.php?id=''])') WHERE TORRENTS LIKE '%:has(\"a[href*=''details.php?id='']\")%';
UPDATE INDEXER_SITES SET TORRENTS = REPLACE(TORRENTS, ':has(\"a\")', ':has(a)') WHERE TORRENTS LIKE '%:has(\"a\")%';
