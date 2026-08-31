SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((movie_keyword CROSS JOIN aka_title) CROSS JOIN cast_info) CROSS JOIN complete_cast) CROSS JOIN keyword) CROSS JOIN movie_info) CROSS JOIN movie_link) CROSS JOIN name) CROSS JOIN title
WHERE aka_title.season_nr = 1
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
