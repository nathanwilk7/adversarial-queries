SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((name CROSS JOIN (title CROSS JOIN cast_info)) CROSS JOIN aka_name) CROSS JOIN info_type) CROSS JOIN char_name) CROSS JOIN movie_info
WHERE char_name.name = 'Himself'
  AND title.imdb_index = 'XII'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id;
