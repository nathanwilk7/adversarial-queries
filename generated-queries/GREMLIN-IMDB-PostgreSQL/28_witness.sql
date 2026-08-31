SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((movie_link CROSS JOIN title) CROSS JOIN kind_type) CROSS JOIN cast_info) CROSS JOIN movie_keyword) CROSS JOIN name) CROSS JOIN aka_name) CROSS JOIN person_info
WHERE kind_type.kind = 'tv series'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
