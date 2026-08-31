SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((((((cast_info CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN movie_link) CROSS JOIN person_info) CROSS JOIN info_type) CROSS JOIN aka_name) CROSS JOIN role_type) CROSS JOIN name) CROSS JOIN movie_info) CROSS JOIN link_type
WHERE info_type.info = 'LD production country'
  AND person_info.note = ''
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
