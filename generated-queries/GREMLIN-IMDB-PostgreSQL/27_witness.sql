SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((movie_companies CROSS JOIN (title CROSS JOIN role_type)) CROSS JOIN movie_link) CROSS JOIN cast_info) CROSS JOIN kind_type) CROSS JOIN name) CROSS JOIN aka_name) CROSS JOIN movie_info
WHERE kind_type.kind = 'tv series'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
