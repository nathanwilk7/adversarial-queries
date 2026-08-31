SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((role_type CROSS JOIN (title CROSS JOIN kind_type)) CROSS JOIN movie_link) CROSS JOIN movie_keyword) CROSS JOIN cast_info) CROSS JOIN movie_info
WHERE kind_type.kind = 'tv series'
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
