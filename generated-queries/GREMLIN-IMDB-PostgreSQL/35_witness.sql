SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((title CROSS JOIN complete_cast) CROSS JOIN (aka_title CROSS JOIN movie_link)) CROSS JOIN cast_info) CROSS JOIN movie_info) CROSS JOIN link_type) CROSS JOIN role_type
WHERE aka_title.production_year = 2003
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
