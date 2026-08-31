SET disabled_optimizers = 'join_order,build_side_probe_side';
SELECT count(*)
FROM (((((((cast_info CROSS JOIN complete_cast) CROSS JOIN aka_name) CROSS JOIN title) CROSS JOIN movie_keyword) CROSS JOIN keyword) CROSS JOIN name) CROSS JOIN comp_cast_type) CROSS JOIN person_info
WHERE comp_cast_type.kind = 'complete+verified'
  AND aka_name.person_id = name.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND complete_cast.status_id = comp_cast_type.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.person_id = name.id;
