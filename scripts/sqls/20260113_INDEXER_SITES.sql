
INSERT INTO INDEXER_SITES (
    ID, NAME, DOMAIN, SEARCH, PARSER, RENDER, PUBLIC, PROXY, SOURCE_TYPE, SEARCH_TYPE, BROWSE, TORRENTS, CATEGORY
) VALUES (
    'azusa', '梓喵', 'https://azusa.wiki/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "querystring", "args": "cat"}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "size": {"selector": "td:nth-child(5)"}, "grabs": {"selector": "td:nth-child(8)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "td[class=\"embedded\"] > b > span[title]", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "table.torrentname > tr > td.embedded", "index": -1}, "labels": {"selector": "table.torrentname > tr > td.embedded > span"}}}', ''
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
    'beitai', '备胎[已死]', 'https://www.beitai.pt/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > table > tr > td.embedded", "contents": -1}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "Movies/\u7535\u5f71"}], "tv": [{"id": 404, "cat": "TV/Documentary", "desc": "Documentaries/\u7eaa\u5f55\u7247"}, {"id": 405, "cat": "TV/Anime", "desc": "Animations/\u52a8\u6f2b"}, {"id": 402, "cat": "TV", "desc": "TV Series/\u5267\u96c6"}, {"id": 403, "cat": "TV", "desc": "TV Shows/\u7efc\u827a"}]}'
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
    'hares', '白兔[已死]', 'https://club.hares.top/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up,img.pro_50pctdown,img.pro_50pctdown2up,img.pro_30pctdown", "attribute": "data-d", "filters": [{"name": "re_search", "args": ["\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "div.layui-torrents-Subject > div.left > p.layui-elip.layui-torrents-descr-width"}, "labels": {"selector": "div.layui-torrents-Subject > div.left > p.layui-elip.layui-torrents-descr-width > span"}}}', ''
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
    'hd', 'HDAI[已死]', 'https://www.hd.ai/', '{"paths": [{"path": "Torrents.index", "method": "chrome", "params": {"keyword": "//input[@name=\"keyword\"]", "submit": "//div[@id=\"search-container\"]//button[@type=\"submit\"]", "script": "document.querySelectorAll(''#search-container'')[0].className += \" layui-show\""}}]}', '', 1, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "div.layui-table-body.layui-table-main > table tr"}, "fields": {"title": {"selector": "a[href*=\"details.php?id=\"] > b"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?hash=\"]", "attribute": "href"}, "date_added": {"selector": "td[data-field=\"added\"]", "attribute": "data-content", "optional": true}, "date_elapsed": {"selector": "td[data-field=\"added\"] > div", "optional": true}, "size": {"selector": "td[data-field=\"size\"] > div"}, "seeders": {"selector": "td[data-field=\"seeders\"] > div"}, "leechers": {"selector": "td[data-field=\"leechers\"] > div"}, "grabs": {"selector": "td[data-field=\"times_completed\"] > div"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "description": {"selector": "td[data-field=\"name\"] > div", "remove": "a,section,img,span", "contents": -1}, "labels": {"selector": "td[data-field=\"name\"] > div > span"}}}', ''
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
    'hd4fans', '兽站[已死]', 'https://pt.hd4fans.org/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > table > tr > td.embedded", "contents": -1}, "labels": {"selector": "td:nth-child(2) > table > tr > td.embedded > span"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "Movies"}], "tv": [{"id": 404, "cat": "TV/Documentary", "desc": "Documentaries"}, {"id": 405, "cat": "TV/Anime", "desc": "Animations"}, {"id": 402, "cat": "TV", "desc": "TV Series"}, {"id": 403, "cat": "TV", "desc": "TV Shows"}]}'
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
    'HDarea', '高清视界', 'https://hdarea.club/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > table > tr > td.embedded", "contents": -1}}}', '{"movie": [{"id": 300, "cat": "Movies/UHD", "desc": "Movies UHD-4K"}, {"id": 401, "cat": "Movies/BluRay", "desc": "Movies Blu-ray"}, {"id": 415, "cat": "Movies/HD", "desc": "Movies REMUX"}, {"id": 416, "cat": "Movies/3D", "desc": "Movies 3D"}, {"id": 410, "cat": "Movies/HD", "desc": "Movies 1080p"}, {"id": 411, "cat": "Movies/HD", "desc": "Movies 720p"}, {"id": 414, "cat": "Movies/DVD", "desc": "Movies DVD"}, {"id": 412, "cat": "Movies/WEB-DL", "desc": "Movies WEB-DL"}, {"id": 413, "cat": "Movies/HD", "desc": "Movies HDTV"}, {"id": 417, "cat": "Movies/Other", "desc": "Movies iPad"}], "tv": [{"id": 404, "cat": "TV/Documentary", "desc": "Documentaries"}, {"id": 405, "cat": "TV/Anime", "desc": "Animations"}, {"id": 402, "cat": "TV", "desc": "TV Series"}, {"id": 403, "cat": "TV", "desc": "TV Shows"}]}'
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
    'hdbd', '伊甸园[已死]', 'https://pt.hdbd.us/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "img[title][src=\"pic/cattrans.gif\"]", "attribute": "title"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "poster": {"text": ""}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > table > tr > td.embedded:has(\"a[title]\")", "remove": "span, a, b"}, "labels": {"selector": "td:nth-child(2) > table > tr > td.embedded:has(\"a[title]\") > span"}}}', ''
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
    'hdvideo', 'HDVIDEO', 'https://hdvideo.top/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "querystring", "args": "cat"}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "poster": {"selector": "img[data-orig]", "attribute": "data-orig"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "size": {"selector": "td.rowfollow:nth-child(5)"}, "grabs": {"selector": "td.rowfollow:nth-child(8)"}, "seeders": {"selector": "td.rowfollow:nth-child(6)"}, "leechers": {"selector": "td.rowfollow:nth-child(7)"}, "date_elapsed": {"selector": "td.rowfollow:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td.rowfollow:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "div > b > span[title]", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "tags": {"selector": "div > a.torrents-tag"}, "subject": {"selector": "td.embedded:nth-child(2) > div > div[style] > span", "contents": -1}, "description": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(1)", "remove": "span,a,img,font,b", "contents": -1}, "labels": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(1) > span"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "\u7535\u5f71"}], "tv": [{"id": 402, "cat": "TV/Series", "desc": "\u7535\u89c6\u5267"}, {"id": 403, "cat": "TV/Shows", "desc": "\u7efc\u827a"}, {"id": 404, "cat": "TV/Documentaries", "desc": "\u7eaa\u5f55\u7247"}, {"id": 405, "cat": "TV/Animations", "desc": "\u52a8\u6f2b"}]}'
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
    'HDZone', '空间[已死]', 'https://hdfun.me/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > table > tr > td.embedded", "contents": -1}, "labels": {"selector": "td:nth-child(2) > table > tr > td.embedded > span"}}}', '{"movie": [{"id": 411, "cat": "Movies/SD", "desc": "Movies SD"}, {"id": 412, "cat": "Movies", "desc": "Movies IPad"}, {"id": 413, "cat": "Movies/HD", "desc": "Movies 720p"}, {"id": 414, "cat": "Movies/HD", "desc": "Movies 1080p"}, {"id": 415, "cat": "Movies", "desc": "Movies REMUX"}, {"id": 450, "cat": "Movies/BluRay", "desc": "Movies Bluray"}, {"id": 499, "cat": "Movies/UHD", "desc": "Movies UHD Blu-ray"}, {"id": 416, "cat": "Movies/UHD", "desc": "Movies 2160p"}], "tv": [{"id": 417, "cat": "TV/Documentary", "desc": "Doc SD"}, {"id": 418, "cat": "TV/Documentary", "desc": "Doc IPad"}, {"id": 419, "cat": "TV/Documentary", "desc": "Doc 720p"}, {"id": 420, "cat": "TV/Documentary", "desc": "Doc 1080p"}, {"id": 421, "cat": "TV/Documentary", "desc": "Doc REMUX"}, {"id": 451, "cat": "TV/Documentary", "desc": "Doc Bluray"}, {"id": 500, "cat": "TV/Documentary", "desc": "Doc UHD Blu-ray"}, {"id": 422, "cat": "TV/Documentary", "desc": "Doc 2160p"}, {"id": 425, "cat": "TV/SD", "desc": "TVShow SD"}, {"id": 426, "cat": "TV", "desc": "TVShow IPad"}, {"id": 471, "cat": "TV", "desc": "TVShow IPad"}, {"id": 427, "cat": "TV/HD", "desc": "TVShow 720p"}, {"id": 472, "cat": "TV/HD", "desc": "TVShow 720p"}, {"id": 428, "cat": "TV/HD", "desc": "TVShow 1080i"}, {"id": 429, "cat": "TV/HD", "desc": "TVShow 1080p"}, {"id": 430, "cat": "TV", "desc": "TVShow REMUX"}, {"id": 452, "cat": "TV/HD", "desc": "TVShow Bluray"}, {"id": 431, "cat": "TV/UHD", "desc": "TVShow 2160p"}, {"id": 432, "cat": "TV/SD", "desc": "TVSeries SD"}, {"id": 433, "cat": "TV", "desc": "TVSeries IPad"}, {"id": 434, "cat": "TV/HD", "desc": "TVSeries 720p"}, {"id": 435, "cat": "TV/HD", "desc": "TVSeries 1080i"}, {"id": 436, "cat": "TV/HD", "desc": "TVSeries 1080p"}, {"id": 437, "cat": "TV", "desc": "TVSeries REMUX"}, {"id": 453, "cat": "TV/HD", "desc": "TVSeries Bluray"}, {"id": 438, "cat": "TV/UHD", "desc": "TVSeries 2160p"}, {"id": 444, "cat": "TV/Anime", "desc": "Anime SD"}, {"id": 445, "cat": "TV/Anime", "desc": "Anime IPad"}, {"id": 446, "cat": "TV/Anime", "desc": "Anime 720p"}, {"id": 447, "cat": "TV/Anime", "desc": "Anime 1080p"}, {"id": 448, "cat": "TV/Anime", "desc": "Anime REMUX"}, {"id": 454, "cat": "TV/Anime", "desc": "Anime Bluray"}, {"id": 449, "cat": "TV/Anime", "desc": "Anime 2160p"}, {"id": 501, "cat": "TV/Anime", "desc": "Anime UHD Blu-ray"}]}'
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
    'icc2022', '冰淇淋[已死]', 'https://www.icc2022.com/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "table.torrentname > tr > td:nth-child(2)", "remove": "a,b,img,span", "contents": -1}, "labels": {"selector": "table.torrentname > tr > td:nth-child(2) > span"}, "minimumratio": {"text": 1}, "minimumseedtime": {"text": 90000}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "Movies/\u7535\u5f71", "default": true}], "tv": [{"id": 404, "cat": "TV/Documentary", "desc": "Documentaries/\u7eaa\u5f55\u7247", "default": true}, {"id": 405, "cat": "TV/Anime", "desc": "Animations/\u52a8\u6f2b", "default": true}, {"id": 402, "cat": "TV", "desc": "TV Series/\u7535\u89c6\u5267", "default": true}, {"id": 403, "cat": "TV", "desc": "TV Shows/\u7efc\u827a", "default": true}]}'
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
    'ihdbits', 'iHDBits[已死]', 'https://ihdbits.me/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "querystring", "args": "cat"}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "poster": {"selector": "img[data-orig]", "attribute": "data-orig"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "size": {"selector": "td.rowfollow:nth-child(5)"}, "grabs": {"selector": "td.rowfollow:nth-child(8)"}, "seeders": {"selector": "td.rowfollow:nth-child(6)"}, "leechers": {"selector": "td.rowfollow:nth-child(7)"}, "date_elapsed": {"selector": "td.rowfollow:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td.rowfollow:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "div > b > span[title]", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "tags": {"selector": "div > a.torrents-tag"}, "subject": {"selector": "td.embedded:nth-child(2) > div > div:nth-child(2) > span", "contents": -1}, "description": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(2)", "remove": "span,a,img,font,b", "contents": -1}, "labels": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(2) > span"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "Movies/\u7535\u5f71"}], "tv": [{"id": 404, "cat": "TV/Documentary", "desc": "Documentaries/\u7eaa\u5f55\u7247"}, {"id": 405, "cat": "TV/Anime", "desc": "Animations/\u52a8\u6f2b"}, {"id": 402, "cat": "TV", "desc": "TV Series/\u8fde\u7eed\u5267"}, {"id": 403, "cat": "TV", "desc": "TV Shows/\u7efc\u827a"}]}'
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
    'jptv', 'JPTV[已死]', 'https://jptv.club/', '{"paths": [{"path": "torrents/filter?search={keyword}", "method": "get"}]}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '{"path": "torrents/filter?page={page}", "start": 1}', '{"list": {"selector": "div.table-responsive > table > tbody > tr"}, "fields": {"id": {"selector": "a.view-torrent", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title": {"selector": "a.view-torrent"}, "details": {"selector": "a.view-torrent", "attribute": "href"}, "download": {"selector": "a[href*=\"torrents/download/\"]", "attribute": "href"}, "date_elapsed": {"selector": "td:nth-child(7) > time"}, "size": {"selector": "td:nth-child(8) > span", "remove": "span"}, "seeders": {"selector": "td:nth-child(9) > a > span"}, "leechers": {"selector": "td:nth-child(10) > a > span"}, "grabs": {"selector": "td:nth-child(11) > a > span", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "downloadvolumefactor": {"case": {"*": 1}}, "uploadvolumefactor": {"case": {"*": 1}}}}', ''
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
    'leaves', '红叶PT[已死]', 'https://leaves.red/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "querystring", "args": "cat"}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "poster": {"selector": "img[data-orig]", "attribute": "data-orig"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "size": {"selector": "td.rowfollow:nth-child(5)"}, "grabs": {"selector": "td.rowfollow:nth-child(8)"}, "seeders": {"selector": "td.rowfollow:nth-child(6)"}, "leechers": {"selector": "td.rowfollow:nth-child(7)"}, "date_elapsed": {"selector": "td.rowfollow:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td.rowfollow:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "div > b > span[title]", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "tags": {"selector": "div > a.torrents-tag"}, "subject": {"selector": "td.embedded:nth-child(2) > div > div:nth-child(2) > span", "contents": -1}, "description": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(2)"}, "labels": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(2) > span", "remove": "span,a,img,font,b", "contents": -1}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "\u7535\u5f71"}], "tv": [{"id": 402, "cat": "TV/Series", "desc": "TV Series (\u5267\u96c6)"}, {"id": 403, "cat": "TV/Shows", "desc": "TV Shows (\u7535\u89c6\u8282\u76ee)"}, {"id": 404, "cat": "TV/Documentaries", "desc": "Documentaries (\u7eaa\u5b9e)"}, {"id": 405, "cat": "TV/Animations", "desc": "Animations (\u52a8\u753b)"}]}'
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
    'lemonhd', '柠檬不酸', 'https://lemonhd.club/', '{"paths": [{"path": "torrents.php", "type": "all", "method": "get"}, {"path": "torrents_movie.php", "type": "movie", "method": "get"}, {"path": "torrents_tv.php", "type": "tv", "method": "get"}, {"path": "torrents_animate.php", "type": "anime", "method": "get"}], "params": {"search": "{keyword}", "stype": "s"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"a[href]\")"}, "fields": {"id": {"selector": "a[href*=\"details_\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "free_deadline": {"selector": "div[style*=\"padding-left\"] > span", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "category": {"selector": "img[class*=\"cat_\"]", "attribute": "class", "filters": [{"name": "replace", "args": ["cat_", ""]}]}, "title_default": {"selector": "a[href*=\"details_\"] > b"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details_\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "details": {"selector": "a[href*=\"details_\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?\"]", "attribute": "href"}, "imdbid": {"selector": "a[href*=\"imdb.com/title/tt\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-last-child(7) > span", "optional": true}, "date_added": {"selector": "td:nth-last-child(7) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-last-child(6)"}, "seeders": {"selector": "td:nth-last-child(5)"}, "leechers": {"selector": "td:nth-last-child(4)"}, "grabs": {"selector": "td:nth-last-child(3)"}, "downloadvolumefactor": {"case": {"div[style*=\"padding-left\"] > span": 0, "div[style*=\"padding-left\"]": 0, "*": 1}}, "uploadvolumefactor": {"case": {"*": 1}}, "description": {"selector": "td:nth-child(3) > div", "index": 1}, "labels": {"selector": "td:nth-child(3) > span"}}}', ''
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
    'ptchina', '铂金学院[已死]', 'https://ptchina.org/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "querystring", "args": "cat"}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "poster": {"selector": "img[data-orig]", "attribute": "data-orig"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "size": {"selector": "td.rowfollow:nth-child(5)"}, "grabs": {"selector": "td.rowfollow:nth-child(8)"}, "seeders": {"selector": "td.rowfollow:nth-child(6)"}, "leechers": {"selector": "td.rowfollow:nth-child(7)"}, "date_elapsed": {"selector": "td.rowfollow:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td.rowfollow:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "div > b > span[title]", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "tags": {"selector": "div > a.torrents-tag"}, "subject": {"selector": "td.embedded:nth-child(2) > div > div[style] > span", "contents": -1}, "description": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(1)", "remove": "span,a,img,font,b", "contents": -1}, "labels": {"selector": "td:nth-child(2) > table.torrentname > tr > td:nth-child(1) > span"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "Movies/\u7535\u5f71"}], "tv": [{"id": 402, "cat": "TV", "desc": "TV Series/\u7535\u89c6\u5267"}, {"id": 404, "cat": "TV/Documentary", "desc": "Documentaries/\u7eaa\u5f55\u7247"}]}'
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
    'pterclub', '猫站', 'https://pterclub.net/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "querystring", "args": "cat"}]}, "title": {"selector": "td:nth-child(2) > div > div:nth-child(1) > a > b"}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "poster": {"selector": "img[data-orig]", "attribute": "data-orig"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "size": {"selector": "td.rowfollow:nth-child(5)"}, "grabs": {"selector": "td.rowfollow:nth-child(8)"}, "seeders": {"selector": "td.rowfollow:nth-child(6)"}, "leechers": {"selector": "td.rowfollow:nth-child(7)"}, "date_elapsed": {"selector": "td.rowfollow:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td.rowfollow:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "div > b > span[title]", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > div > div:nth-child(2) > span"}, "labels": {"selector": "td:nth-child(2) > div > div:nth-child(2) > a.torrents-tag"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "\u7535\u5f71 (Movie)"}], "tv": [{"id": 404, "cat": "TV", "desc": "\u7535\u89c6\u5267 (TV Play)"}, {"id": 403, "cat": "TV/Anime", "desc": "\u52a8\u6f2b (Anime)"}, {"id": 405, "cat": "TV", "desc": "\u7efc\u827a (TV Show)"}, {"id": 402, "cat": "TV/Documentary", "desc": "\u7eaa\u5f55\u7247 (Documentary)"}]}'
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
    'PTMSG', '马杀鸡[已死]', 'https://pt.msg.vg/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "td:nth-child(2) > table > tr > td:nth-child(1)", "remove": "b, a, font, span", "contents": -1}, "labels": {"selector": "td:nth-child(2) > table > tr > td:nth-child(1) > span"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "Movies/\u7535\u5f71"}], "tv": [{"id": 404, "cat": "TV/Documentary", "desc": "Documentaries/\u7eaa\u5f55\u7247"}, {"id": 405, "cat": "TV/Anime", "desc": "Animations/\u52a8\u6f2b"}, {"id": 402, "cat": "TV", "desc": "TV Series/\u5267\u96c6"}, {"id": 403, "cat": "TV", "desc": "TV Shows/\u7efc\u827a"}]}'
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
    'sharkpt', '鲨鱼[已死]', 'https://sharkpt.net/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "div.s-table-body-item > div.torrent-item"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title": {"selector": "div.torrent-title > a"}, "details": {"selector": "div.torrent-title > a", "attribute": "href"}, "download": {"selector": "shark-icon.torrent-action-download", "attribute": "onclick", "filters": [{"name": "re_search", "args": ["download.php\\?id=\\d+", 0]}]}, "size": {"selector": "div.torrent-size"}, "grabs": {"selector": "div.torrent-snatches > a"}, "seeders": {"selector": "div.torrent-seeders > a"}, "leechers": {"selector": "div.torrent-leechers > a"}, "date_elapsed": {"selector": "div.torrent-when > span"}, "date_added": {"selector": "div.torrent-when > span", "attribute": "title"}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "downloadvolumefactor": {"case": {"font.free": 0, "font.twoupfree": 0, "*": 1}}, "uploadvolumefactor": {"case": {"font.twoupfree": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "div.torrent-tags > font > span", "attribute": "title", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "tags": {"selector": "div > a.torrents-tag"}, "description": {"selector": "div.torrent-subtitle"}, "labels": {"selector": "div.torrent-tags > span > a.s-tag"}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "\u7535\u5f71"}], "tv": [{"id": 402, "cat": "TV/Series", "desc": "\u7535\u89c6\u5267"}, {"id": 403, "cat": "TV/Shows", "desc": "\u7efc\u827a"}, {"id": 404, "cat": "TV/Documentaries", "desc": "\u7eaa\u5f55\u7247"}, {"id": 405, "cat": "TV/Animations", "desc": "\u52a8\u6f2b"}]}'
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
    'torrentleech', 'TorrentLeech', 'https://www.tleechreload.org/', '', 'TorrentLeech', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '', ''
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
    'uploads', 'upload', 'https://upload.cx/', '{"paths": [{"path": "torrents.php", "method": "get"}], "params": {"search": "{keyword}"}, "batch": {"delimiter": " ", "space_replace": "_"}}', '', 0, 0, 0, 'MOVIE,TV,ANIME', 'title', '', '{"list": {"selector": "table.torrents > tr:has(\"table.torrentname\")"}, "fields": {"id": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href", "filters": [{"name": "re_search", "args": ["\\d+", 0]}]}, "title_default": {"selector": "a[href*=\"details.php?id=\"]"}, "title_optional": {"optional": true, "selector": "a[title][href*=\"details.php?id=\"]", "attribute": "title"}, "title": {"text": "{% if fields[''title_optional''] %}{{ fields[''title_optional''] }}{% else %}{{ fields[''title_default''] }}{% endif %}"}, "category": {"selector": "a[href*=\"?cat=\"]", "attribute": "href", "filters": [{"name": "replace", "args": ["?", ""]}, {"name": "querystring", "args": "cat"}]}, "details": {"selector": "a[href*=\"details.php?id=\"]", "attribute": "href"}, "download": {"selector": "a[href*=\"download.php?id=\"]", "attribute": "href"}, "imdbid": {"selector": "div.imdb_100 > a", "attribute": "href", "filters": [{"name": "re_search", "args": ["tt\\d+", 0]}]}, "date_elapsed": {"selector": "td:nth-child(4) > span", "optional": true}, "date_added": {"selector": "td:nth-child(4) > span", "attribute": "title", "optional": true}, "date": {"text": "{% if fields[''date_elapsed''] or fields[''date_added''] %}{{ fields[''date_elapsed''] if fields[''date_elapsed''] else fields[''date_added''] }}{% else %}now{% endif %}", "filters": [{"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "size": {"selector": "td:nth-child(5)"}, "seeders": {"selector": "td:nth-child(6)"}, "leechers": {"selector": "td:nth-child(7)"}, "grabs": {"selector": "td:nth-child(8)"}, "downloadvolumefactor": {"case": {"img.pro_free": 0, "img.pro_free2up": 0, "img.pro_50pctdown": 0.5, "img.pro_50pctdown2up": 0.5, "img.pro_30pctdown": 0.3, "*": 1}}, "uploadvolumefactor": {"case": {"img.pro_50pctdown2up": 2, "img.pro_free2up": 2, "img.pro_2up": 2, "*": 1}}, "free_deadline": {"default_value": "{% if fields[''downloadvolumefactor'']==0 %}{{max_time}}{% endif%}", "default_value_format": "%Y-%m-%d %H:%M:%S.%f", "selector": "img.pro_free,img.pro_free2up", "attribute": "onmouseover", "filters": [{"name": "re_search", "args": ["\\d+-\\d+-\\d+ \\d+:\\d+:\\d+", 0]}, {"name": "dateparse", "args": "%Y-%m-%d %H:%M:%S"}]}, "description": {"selector": "table.torrentname > tr > td:nth-child(2)", "remove": "a,b,img,span", "contents": -1}, "labels": {"selector": "table.torrentname > tr > td:nth-child(2) > span"}, "minimumratio": {"text": 1}, "minimumseedtime": {"text": 90000}}}', '{"movie": [{"id": 401, "cat": "Movies", "desc": "\u7535\u5f71"}], "tv": [{"id": 402, "cat": "TV/Series", "desc": "\u7535\u89c6\u5267"}, {"id": 403, "cat": "TV/Shows", "desc": "\u7efc\u827a"}, {"id": 404, "cat": "TV/Documentaries", "desc": "\u7eaa\u5f55\u7247"}, {"id": 405, "cat": "TV/Animations", "desc": "\u52a8\u6f2b"}]}'
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

