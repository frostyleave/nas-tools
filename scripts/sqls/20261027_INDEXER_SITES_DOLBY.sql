UPDATE "INDEXER_SITES" SET "DOMAIN" = 'https://www.uhddolby.com/' WHERE "ID" = 'hddolby';
UPDATE "SITE_USER_SEEDING_INFO" SET "URL" = 'https://www.uhddolby.com' WHERE "URL" = 'https://www.hddolby.com';
UPDATE "SITE_USER_INFO_STATS" SET "URL" = 'https://www.uhddolby.com' WHERE "URL" = 'https://www.hddolby.com';
UPDATE "SITE_STATISTICS_HISTORY" SET "URL" = 'https://www.uhddolby.com' WHERE "URL" = 'https://www.hddolby.com';
UPDATE "CONFIG_SITE" SET "RSSURL" = REPLACE("RSSURL", 'https://www.hddolby.com', 'https://www.uhddolby.com') WHERE "RSSURL"  LIKE 'https://www.hddolby.com%';
UPDATE "CONFIG_SITE" SET "SIGNURL" = REPLACE("SIGNURL", 'https://www.hddolby.com', 'https://www.uhddolby.com') WHERE "SIGNURL" LIKE 'https://www.hddolby.com%';