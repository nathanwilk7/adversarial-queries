SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((name CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN movie_link) CROSS JOIN kind_type) CROSS JOIN aka_name) CROSS JOIN movie_keyword
WHERE kind_type.kind = 'movie'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
