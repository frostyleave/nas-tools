INSERT INTO INDEXER_SITES (
    ID, NAME, DOMAIN, SEARCH, PARSER, RENDER, PUBLIC, PROXY, SOURCE_TYPE, SEARCH_TYPE, BROWSE, TORRENTS, CATEGORY
) VALUES (
    'hhanclub', '憨憨', 'https://hhanclub.net/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV', 'title', '', '{"a":"hanhan","list":{"selector":"div.torrent-table-sub-info"},"fields":{"id":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href","filters":[{"name":"re_search","args":["\\d+",0]}]},"category":{"selector":"a[href*=\"?cat[]=\"]","attribute":"href","filters":[{"name":"querystring","args":"cat[]"}]},"title_default":{"selector":"a[href*=\"details.php?id=\"]"},"title_optional":{"optional":true,"selector":"a[title][href*=\"details.php?id=\"]","attribute":"title"},"title":{"text":"{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"},"details":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href"},"download":{"selector":"a[href*=\"download.php?id=\"]","attribute":"href"},"size":{"selector":"div.torrent-info-text-size"},"seeders":{"selector":"div.torrent-info-text-seeders > a[href*=\"#seeders\"]"},"leechers":{"selector":"div.torrent-info-text-leechers > a[href*=\"#leechers\"]"},"date_elapsed":{"selector":"div.torrent-info-text-added > span","optional":true},"date_added":{"selector":"div.torrent-info-text-added > span","attribute":"title","optional":true},"date":{"text":"{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}","filters":[{"name":"dateparse","args":"%Y-%m-%d %H:%M:%S"}]},"downloadvolumefactor":{"case":{"span.promotion-tag-free":0,"span.promotion-tag-free2up":0,"span.promotion-tag-50pctdown":0.5,"span.promotion-tag-50pctdown2up":0.5,"span.promotion-tag-30pctdown":0.3,"*":1}},"uploadvolumefactor":{"case":{"span.promotion-tag-50pctdown2up":2,"span.promotion-tag-free2up":2,"span.promotion-tag-2up":2,"*":1}},"description":{"selector":"div.torrent-info-text-small_name"},"labels":{"selector":"a > span.tag"},"freedate":{"selector":"span.flex > span[title]","attribute":"title"}}}', '{"field":"cat[]","delimiter":"&cat[]=","movie":[{"id":401,"cat":"Movies","desc":"Movies/电影"}],"tv":[{"id":404,"cat":"TV/Documentary","desc":"Documentaries/纪录片"},{"id":405,"cat":"TV/Anime","desc":"Animations/动漫"},{"id":402,"cat":"TV","desc":"TV Series/连续剧"},{"id":403,"cat":"TV","desc":"TV Shows/综艺"}]}'
)
ON CONFLICT(ID) DO UPDATE SET
    NAME = excluded.NAME,
    DOMAIN = excluded.DOMAIN,
    SEARCH = excluded.SEARCH,
    PARSER = excluded.PARSER,
    RENDER = excluded.RENDER,
    PROXY = excluded.PROXY,
    SOURCE_TYPE = excluded.SOURCE_TYPE,
    SEARCH_TYPE = excluded.SEARCH_TYPE,
    BROWSE = excluded.BROWSE,
    TORRENTS = excluded.TORRENTS,
    CATEGORY = excluded.CATEGORY;

INSERT INTO INDEXER_SITES (
    ID, NAME, DOMAIN, SEARCH, PARSER, RENDER, PUBLIC, PROXY, SOURCE_TYPE, SEARCH_TYPE, BROWSE, TORRENTS, CATEGORY
) VALUES (
    'ourbits', '我堡', 'https://ourbits.club/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list":{"selector":"table.torrents > tr:has(\"table.torrentname\")"},"fields":{"id":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href","filters":[{"name":"re_search","args":["\\d+",0]}]},"category":{"selector":"a[href*=\"?cat=\"]","attribute":"href","filters":[{"name":"querystring","args":"cat"}]},"title_default":{"selector":"a[href*=\"details.php?id=\"]"},"title_optional":{"optional":true,"selector":"a[title][href*=\"details.php?id=\"]","attribute":"title"},"title":{"text":"{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"},"details":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href"},"download":{"selector":"a[href*=\"download.php?id=\"]","attribute":"href"},"size":{"selector":"td:nth-child(5)","index":1},"grabs":{"selector":"td:nth-child(8)"},"seeders":{"selector":"td:nth-child(6)"},"leechers":{"selector":"td:nth-child(7)"},"date_elapsed":{"selector":"td:nth-child(4) > span","attribute":"title","optional":true},"date_added":{"selector":"td:nth-child(4) > span","attribute":"title","optional":true},"date":{"text":"{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}","filters":[{"name":"dateparse","args":"%Y-%m-%d %H:%M:%S"}]},"downloadvolumefactor":{"case":{"img.pro_free":0,"img.pro_free2up":0,"img.pro_50pctdown":0.5,"img.pro_50pctdown2up":0.5,"img.pro_30pctdown":0.3,"*":1}},"uploadvolumefactor":{"case":{"img.pro_50pctdown2up":2,"img.pro_free2up":2,"img.pro_2up":2,"*":1}},"free_deadline":{"default_value":"{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}","default_value_format":"%Y-%m-%d %H:%M:%S.%f","selector":"td[class=\"embedded\"] > b > span[title]","attribute":"title","filters":[{"name":"dateparse","args":"%Y-%m-%d %H:%M:%S"}]},"tags":{"selector":"table.torrentname > tr > td.embedded > div:has(\"a\")"},"subject":{"selector":"table.torrentname > tr > td.embedded","remove":"div,a,img,b"},"description":{"text":"{% if fields[''tags'']%}{{ fields[''subject'']+'' ''+fields[''tags''] }}{% else %}{{ fields[''subject''] }}{% endif %}"},"labels":{"selector":"table.torrentname > tr > td.embedded > div > a > div.tag"},"hr":["//h1[@id=''top'']/img[@class=''hitandrun'']"]}}', '{"field":"cat[]","delimiter":"&cat[]=","movie": [{"id": 401, "cat": "Movies", "desc": "Movies"}, {"id": 402, "cat": "Movies/3D", "desc": "Movies 3D"}], "tv": [{"id": 405, "cat": "TV", "desc": "TV Packs"}, {"id": 410, "cat": "TV/Documentary", "desc": "Documentaries"}, {"id": 411, "cat": "TV/Anime", "desc": "Animations"}, {"id": 412, "cat": "TV", "desc": "TV Episodes"}, {"id": 413, "cat": "TV", "desc": "TV Shows"}, {"id": 419, "cat": "TV", "desc": "Concert"}]}'
)
ON CONFLICT(ID) DO UPDATE SET
    NAME = excluded.NAME,
    DOMAIN = excluded.DOMAIN,
    SEARCH = excluded.SEARCH,
    PARSER = excluded.PARSER,
    RENDER = excluded.RENDER,
    PROXY = excluded.PROXY,
    SOURCE_TYPE = excluded.SOURCE_TYPE,
    SEARCH_TYPE = excluded.SEARCH_TYPE,
    BROWSE = excluded.BROWSE,
    TORRENTS = excluded.TORRENTS,
    CATEGORY = excluded.CATEGORY;