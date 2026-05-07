INSERT INTO INDEXER_SITES (
    ID, NAME, DOMAIN, SEARCH, PARSER, RENDER, PUBLIC, PROXY, SOURCE_TYPE, SEARCH_TYPE, BROWSE, TORRENTS, CATEGORY
) VALUES (
    'audiences', '观众', 'https://audiences.me/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list":{"selector":"table.torrents > tr:has(\"table.torrentname\")"},"fields":{"id":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href","filters":[{"name":"re_search","args":["\\d+",0]}]},"title_default":{"selector":"a[href*=\"details.php?id=\"]"},"title_optional":{"optional":true,"selector":"a[title][href*=\"details.php?id=\"]","attribute":"title"},"title":{"text":"{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"},"category":{"selector":"a[href*=\"?cat=\"]","attribute":"href","filters":[{"name":"replace","args":["?",""]},{"name":"querystring","args":"cat"}]},"details":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href"},"download":{"selector":"a[href*=\"download.php?id=\"]","attribute":"href"},"imdbid":{"selector":"div.imdb_100 > a","attribute":"href","filters":[{"name":"re_search","args":["tt\\d+",0]}]},"date_elapsed":{"selector":"td:nth-child(4) > span","optional":true},"date_added":{"selector":"td:nth-child(4) > span","attribute":"title","optional":true},"date":{"text":"{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}","filters":[{"name":"dateparse","args":"%Y-%m-%d %H:%M:%S"}]},"size":{"selector":"td:nth-child(5)"},"seeders":{"selector":"td:nth-child(6)"},"leechers":{"selector":"td:nth-child(7)"},"grabs":{"selector":"td:nth-child(8)"},"downloadvolumefactor":{"case":{"img.pro_free":0,"img.pro_free2up":0,"img.pro_50pctdown":0.5,"img.pro_50pctdown2up":0.5,"img.pro_30pctdown":0.3,"*":1}},"uploadvolumefactor":{"case":{"img.pro_50pctdown2up":2,"img.pro_free2up":2,"img.pro_2up":2,"*":1}},"free_deadline":{"default_value":"{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}","default_value_format":"%Y-%m-%d %H:%M:%S.%f","selector":"img.pro_free,img.pro_free2up","attribute":"onmouseover","filters":[{"name":"re_search","args":["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+",0]},{"name":"dateparse","args":"%Y-%m-%d %H:%M:%S"}]},"description":{"selector":"span.torrent-subtitle-text"},"labels":{"selector":"span.torrent-subtitle-tags> span.tags"}}}', '{"movie":[{"id":401,"cat":"Movies","desc":"电影/Movies"}],"tv":[{"id":402,"cat":"TV","desc":"剧集/TV-Series"},{"id":403,"cat":"TV","desc":"综艺/TV-Show"},{"id":406,"cat":"TV/Documentary","desc":"纪录片/Documentary"}]}'
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
