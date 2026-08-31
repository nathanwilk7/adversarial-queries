SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((((cast_info CROSS JOIN movie_keyword) CROSS JOIN title) CROSS JOIN keyword) CROSS JOIN char_name) CROSS JOIN name) CROSS JOIN person_info) CROSS JOIN info_type) CROSS JOIN aka_name) CROSS JOIN movie_info) CROSS JOIN complete_cast
WHERE aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND complete_cast.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
