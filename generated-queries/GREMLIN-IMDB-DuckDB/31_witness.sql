SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((cast_info CROSS JOIN char_name) CROSS JOIN title) CROSS JOIN aka_name) CROSS JOIN name) CROSS JOIN role_type) CROSS JOIN person_info
WHERE char_name.name = 'Himself'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.person_role_id = char_name.id
  AND cast_info.role_id = role_type.id
  AND person_info.person_id = name.id;
