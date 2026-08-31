SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((movie_link CROSS JOIN aka_title) CROSS JOIN complete_cast) CROSS JOIN info_type) CROSS JOIN keyword) CROSS JOIN link_type) CROSS JOIN movie_info) CROSS JOIN movie_keyword) CROSS JOIN person_info) CROSS JOIN title
WHERE aka_title.season_nr = 2
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id;
