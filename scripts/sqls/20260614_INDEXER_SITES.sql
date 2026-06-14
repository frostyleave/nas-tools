INSERT INTO INDEXER_SITES (
    "ID", "NAME", "DOMAIN", "SEARCH", "PARSER", "RENDER", "PUBLIC", "PROXY", "SOURCE_TYPE", "SEARCH_TYPE", "BROWSE", "TORRENTS", "CATEGORY", "EXTRA"
) VALUES (
    'cspt', '财神', 'https://cspt.top/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list":{"selector":"div.torrent-table-sub-info"},"fields":{"id":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href","filters":[{"name":"re_search","args":["\\d+",0]}]},"category":{"selector":"a[href*=\"?cat[]=\"]","attribute":"href","filters":[{"name":"querystring","args":"cat[]"}]},"title_default":{"selector":"a[href*=\"details.php?id=\"]"},"title_optional":{"optional":true,"selector":"a[title][href*=\"details.php?id=\"]","attribute":"title"},"title":{"text":"{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"},"details":{"selector":"a[href*=\"details.php?id=\"]","attribute":"href"},"download":{"selector":"a[href*=\"download.php?id=\"]","attribute":"href"},"size":{"selector":"div.torrent-info-text-size"},"seeders":{"selector":"div.torrent-info-text-seeders>b>a[href*=\"#seeders\"]"},"leechers":{"selector":"div.torrent-info-text-leechers>b>a[href*=\"#leechers\"]"},"date_elapsed":{"selector":"div.torrent-info-text-added > span","optional":true},"date_added":{"selector":"div.torrent-info-text-added > span","attribute":"title","optional":true},"date":{"text":"{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}","filters":[{"name":"dateparse","args":"%Y-%m-%d %H:%M:%S"}]},"downloadvolumefactor":{"case":{"span.promotion-tag-free":0,"span.promotion-tag-free2up":0,"span.promotion-tag-50pctdown":0.5,"span.promotion-tag-50pctdown2up":0.5,"span.promotion-tag-30pctdown":0.3,"*":1}},"uploadvolumefactor":{"case":{"span.promotion-tag-50pctdown2up":2,"span.promotion-tag-free2up":2,"span.promotion-tag-2up":2,"*":1}},"description":{"selector":"div.torrent-info-text-small_name"},"labels":{"selector":"a > span.tag"},"freedate":{"selector":"span.flex > span[title]","attribute":"title"}}}', '{"movie":[{"id":401,"cat":"Movies","desc":"Movies/电影"}],"tv":[{"id":404,"cat":"TV/Documentary","desc":"Documentaries/纪录片"},{"id":405,"cat":"TV/Anime","desc":"Animations/动漫"},{"id":402,"cat":"TV","desc":"TV Series/连续剧"},{"id":403,"cat":"TV","desc":"TV Shows/综艺"}]}'
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
