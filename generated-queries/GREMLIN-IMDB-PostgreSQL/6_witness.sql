SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((cast_info CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN char_name) CROSS JOIN kind_type) CROSS JOIN role_type) CROSS JOIN name) CROSS JOIN movie_info) CROSS JOIN info_type) CROSS JOIN aka_name
WHERE char_name.name = 'Himself'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND title.kind_id = kind_type.id;
