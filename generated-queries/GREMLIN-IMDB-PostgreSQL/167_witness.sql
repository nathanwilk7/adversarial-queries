SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((title CROSS JOIN kind_type) CROSS JOIN aka_title) CROSS JOIN cast_info) CROSS JOIN movie_info) CROSS JOIN movie_link) CROSS JOIN role_type
WHERE kind_type.kind = 'tv series'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
