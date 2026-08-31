SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((cast_info CROSS JOIN aka_name) CROSS JOIN title) CROSS JOIN char_name) CROSS JOIN info_type) CROSS JOIN kind_type) CROSS JOIN name) CROSS JOIN movie_info) CROSS JOIN person_info
WHERE char_name.name = 'Himself'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id
  AND title.kind_id = kind_type.id;
