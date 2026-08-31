SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((((title CROSS JOIN movie_link) CROSS JOIN movie_companies) CROSS JOIN movie_info) CROSS JOIN info_type) CROSS JOIN aka_title) CROSS JOIN cast_info) CROSS JOIN kind_type) CROSS JOIN movie_keyword) CROSS JOIN person_info) CROSS JOIN role_type
WHERE aka_title.title = 'Anonima ricatti'
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND title.kind_id = kind_type.id;
