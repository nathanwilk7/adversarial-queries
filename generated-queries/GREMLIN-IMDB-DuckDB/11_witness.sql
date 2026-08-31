SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM ((((((cast_info CROSS JOIN movie_keyword) CROSS JOIN title) CROSS JOIN name) CROSS JOIN role_type) CROSS JOIN keyword) CROSS JOIN aka_name) CROSS JOIN person_info
WHERE cast_info.nr_order = 0
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
