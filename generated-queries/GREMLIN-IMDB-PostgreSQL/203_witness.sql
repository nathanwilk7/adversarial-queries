SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((kind_type CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN info_type) CROSS JOIN person_info) CROSS JOIN role_type) CROSS JOIN name) CROSS JOIN cast_info
WHERE info_type.info = 'genres'
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
