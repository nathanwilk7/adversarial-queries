SET join_collapse_limit = 1;
SELECT count(*)
FROM movie_keyword CROSS JOIN (((((((title CROSS JOIN complete_cast) CROSS JOIN cast_info) CROSS JOIN movie_companies) CROSS JOIN aka_title) CROSS JOIN movie_link) CROSS JOIN movie_info) CROSS JOIN role_type)
WHERE aka_title.episode_nr = 1
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id;
